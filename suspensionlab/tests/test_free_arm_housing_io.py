"""Independent housing model and explicitly versioned, lossless file boundary."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft
from suspensionlab.model.free_arm_housing import FreeArmBallHousing, FreeArmHousingDraft, FreeArmHousingError
from suspensionlab.model.free_arm_housing_io import (
    FreeArmHousingFileError,
    from_data,
    read_free_arm_housing,
    read_independent_arm,
    to_data,
    write_free_arm_housing,
)
from suspensionlab.model.free_arm_io import FreeArmFileError, read_free_arm, write_free_arm
from suspensionlab.model.free_arm_io import to_data as arm_data


def make_draft(bent=()):
    arm = FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2,
                       FreeArmBend((150, 20, 50), 20) if 'front' in bent else None,
                       FreeArmBend((150, 180, -40), 20) if 'rear' in bent else None)
    return FreeArmHousingDraft(arm, FreeArmBallHousing(120, 30, 200, (0, 0, 1), (10, -30, 12)))


@pytest.mark.parametrize('bent', [(), ('front',), ('rear',), ('front', 'rear')])
def test_centerlines_and_roundtrip(tmp_path, bent):
    draft = make_draft(bent)
    paths = draft.centerlines()
    assert all(path[-1] == pytest.approx((310, 70, 22)) for path in paths)
    assert paths[0][0] == draft.arm.front_mm and paths[1][0] == draft.arm.rear_mm
    data = to_data(draft)
    before = deepcopy(data)
    assert from_data(data) == draft and data == before
    path = write_free_arm_housing(tmp_path / 'arm.slarm', draft)
    assert read_free_arm_housing(path) == draft
    assert read_independent_arm(path) == draft
    with pytest.raises(FreeArmFileError):
        read_free_arm(path)  # old reader must never drop the housing
    with pytest.raises(FreeArmHousingFileError):
        write_free_arm_housing(path, draft)
    assert read_free_arm_housing(path) == draft
    with pytest.raises(FrozenInstanceError):
        draft.housing.length_mm = 1


def test_v1_remains_separate_and_readable(tmp_path):
    arm = make_draft().arm
    path = write_free_arm(tmp_path / 'arm.slarm', arm)
    assert read_free_arm(path) == arm
    assert read_independent_arm(path) == arm
    with pytest.raises(FreeArmHousingFileError):
        read_free_arm_housing(path)
    with pytest.raises(FreeArmHousingFileError):
        from_data(arm_data(arm))


@pytest.mark.parametrize('key,value', [
    ('axis', [0, 0, 0]), ('axis', [1, 2]), ('axis', [float('nan'), 0, 1]),
    ('offset_mm', [0, float('inf'), 0]), ('length_mm', True), ('bore_diameter_mm', 120),
    ('outer_diameter_mm', -1),
])
def test_invalid_housing_parameters_are_rejected(key, value):
    data = to_data(make_draft())
    data['ball_housing'][key] = value
    with pytest.raises(FreeArmHousingFileError):
        from_data(data)


def test_bad_offset_and_invalid_bent_path_are_rejected():
    draft = make_draft(('front',))
    with pytest.raises(FreeArmHousingError):
        replace(draft, housing=replace(draft.housing, offset_mm=(-300, -100, -10)))
    with pytest.raises(FreeArmHousingError):
        replace(draft, housing=replace(draft.housing, offset_mm=(-150, -80, 40)))


@pytest.mark.parametrize('mutate', [
    lambda d: d.update(version='3'), lambda d: d.update(source='snapshot'),
    lambda d: d.update(extra=1), lambda d: d['ball_housing'].update(extra=1),
    lambda d: d.pop('ball_housing'), lambda d: d['tube'].update(wall_mm=True),
])
def test_invalid_document_cannot_be_accepted(mutate):
    data = to_data(make_draft())
    mutate(data)
    with pytest.raises(FreeArmHousingFileError):
        from_data(data)


def test_duplicate_keys_nonfinite_and_wrong_extension_are_rejected(tmp_path):
    path = tmp_path / 'bad.slarm'
    path.write_text('{"version":"2", "version":"2"}', encoding='utf-8')
    with pytest.raises(FreeArmHousingFileError):
        read_free_arm_housing(path)
    path.write_text('{"version":NaN}', encoding='utf-8')
    with pytest.raises(FreeArmHousingFileError):
        read_free_arm_housing(path)
    with pytest.raises(FreeArmHousingFileError):
        write_free_arm_housing(tmp_path / 'bad.json', make_draft())
