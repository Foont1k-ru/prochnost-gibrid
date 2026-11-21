"""Проверка списка операций без загрузки CAD-ядра."""
from copy import deepcopy

import pytest

from suspensionlab.core import cad_tube_notch_sequence as sequence
from suspensionlab.core.cad_tube_notch import TubeNotchError
from suspensionlab.core.cad_tube_notch_sequence import TubeNotchSequenceError
from suspensionlab.model.entities import Project
from suspensionlab.model.scheme_arm_assembly import make_scheme_arm_assembly


def document():
    return make_scheme_arm_assembly(Project.create_default(), 10, 2,
                                    {'axis': 'x', 'outer_radius_mm': 14,
                                     'bore_radius_mm': 7, 'length_mm': 24})


@pytest.mark.parametrize(('cutters', 'code', 'index'), [
    (['housing_front', 'housing_front'], 'duplicate_cutter', 1),
    (['housing_front', 'tube_front'], 'same_tube', 1),
    (['housing_front', 'ball_plate'], 'missing_plate', 1),
    (['housing_front', 'unknown'], 'unsupported_pair', 1),
    (['housing_front', None], 'unsupported_pair', 1),
])
def test_invalid_later_step_fails_before_any_cad_work(monkeypatch, cutters, code, index):
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid sequence must not start CAD')
    monkeypatch.setattr(sequence, 'build_part', forbidden)
    doc = document()
    saved, order = deepcopy(doc), deepcopy(cutters)
    with pytest.raises(TubeNotchSequenceError, match=code) as error:
        sequence.notch_tube_sequence(doc, 'tube_front', cutters)
    assert error.value.step_index == index
    assert error.value.cutter_id == str(cutters[index])
    assert doc == saved and cutters == order
    assert not hasattr(error.value, 'shape')


@pytest.mark.parametrize('cutters', [[], (), 'housing_front', ['housing_front'] * 5, None])
def test_sequence_must_be_bounded_nonempty_list_or_tuple(cutters):
    with pytest.raises(TubeNotchError, match='invalid_sequence'):
        sequence.notch_tube_sequence(document(), 'tube_front', cutters)


def test_invalid_target_rejected():
    with pytest.raises(TubeNotchError, match='unsupported_pair'):
        sequence.notch_tube_sequence(document(), 'housing_front', ['housing_rear'])
