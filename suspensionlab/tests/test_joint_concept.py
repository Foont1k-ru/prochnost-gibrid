"""Параметрические условные узлы — только численная геометрия."""
from copy import deepcopy

import pytest

from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept, validate_joint_concept
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document


@pytest.mark.parametrize('kind', ['ball', 'bushing'])
def test_snapshot_roundtrip_and_independent_parameters(kind, tmp_path):
    params = deepcopy(DEFAULTS[kind])
    doc = make_joint_concept(kind, params, name='Узел — черновик')
    params['pin_radius_mm'] = 2
    assert doc['parameters'] != params
    path = tmp_path / f'{kind}.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    assert read_document(path, 'assembly') == doc
    before = path.read_bytes()
    with pytest.raises(KimFormatError):
        write_document(path, 'assembly', doc, overwrite=False)
    assert path.read_bytes() == before


@pytest.mark.parametrize('kind,change', [
    ('ball', ('ball_radius_mm', 14)), ('ball', ('opening_radius_mm', 13)),
    ('ball', ('opening_radius_mm', 5)), ('ball', ('pin_length_mm', 22)),
    ('bushing', ('pin_radius_mm', 7)), ('bushing', ('outer_radius_mm', 7)),
    ('bushing', ('pin_length_mm', 24)), ('ball', ('pin_radius_mm', float('nan'))),
    ('ball', ('outer_radius_mm', True)), ('bushing', ('body_length_mm', 501)),
])
def test_invalid_inputs_are_rejected(kind, change):
    doc = make_joint_concept(kind, DEFAULTS[kind])
    doc['parameters'][change[0]] = change[1]
    with pytest.raises(KimFormatError):
        validate_joint_concept(doc)


def test_strict_schema_rejects_untrusted_fields_and_unknown_algorithms():
    doc = make_joint_concept('ball', DEFAULTS['ball'])
    for patch in ({'extra': 'untrusted.step'}, {'algorithm': 'unknown'}, {'joint_type': []}, {'units': 'inches'}):
        with pytest.raises(KimFormatError):
            validate_joint_concept(doc | patch)
    broken = deepcopy(doc)
    del broken['parameters']['pin_radius_mm']
    with pytest.raises(KimFormatError):
        validate_joint_concept(broken)
