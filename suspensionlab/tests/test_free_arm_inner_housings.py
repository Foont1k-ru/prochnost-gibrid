"""Независимые корпуса: формат, атомарность и строгая проверка входа."""
from copy import deepcopy

import pytest
from test_free_arm_housing_io import make_draft

from suspensionlab.model.free_arm_housing_io import from_data as v2_from_data
from suspensionlab.model.free_arm_housing_io import read_independent_arm
from suspensionlab.model.free_arm_inner_housings import (
    FreeArmInnerHousing,
    FreeArmInnerHousingDraft,
    FreeArmInnerHousings,
)
from suspensionlab.model.free_arm_inner_housings_io import (
    FreeArmInnerHousingFileError,
    from_data,
    to_data,
    write_free_arm_inner_housings,
)
from suspensionlab.model.free_arm_io import from_data as v1_from_data


def make_inner(*, cuts=True, ball=False, bent=()):
    existing = make_draft(bent)
    front = FreeArmInnerHousing(40, 25, 32, (0, 0, 1), True)
    rear = FreeArmInnerHousing(52, 31, 44, (0, 0, 1), True)
    return FreeArmInnerHousingDraft(existing.arm, FreeArmInnerHousings(front, rear, 1 if cuts else None, 0 if cuts else None),
                                    existing.housing if ball else None)


@pytest.mark.parametrize('ball', [False, True])
@pytest.mark.parametrize('cuts', [False, True])
def test_roundtrip_and_old_readers_reject(tmp_path, ball, cuts):
    draft = make_inner(cuts=cuts, ball=ball, bent=('front',))
    data = to_data(draft)
    before = deepcopy(data)
    assert data['version'] == '3' and data['source'] == 'independent'
    assert from_data(data) == draft and data == before
    with pytest.raises(ValueError):
        v1_from_data(data)
    with pytest.raises(ValueError):
        v2_from_data(data)
    path = write_free_arm_inner_housings(tmp_path / 'v3.slarm', draft)
    assert read_independent_arm(path) == draft
    with pytest.raises(FreeArmInnerHousingFileError):
        write_free_arm_inner_housings(path, draft)
    assert read_independent_arm(path) == draft


@pytest.mark.parametrize('mutation', [
    lambda d: d['inner_housings']['front'].update(center_on_pivot=False),
    lambda d: d['inner_housings']['rear'].update(axis=[0, 0, 0]),
    lambda d: d['inner_housings']['rear'].update(bore_diameter_mm=52),
    lambda d: d.update(notches={}),
    lambda d: d.update(notches={'front': True}),
    lambda d: d.update(notches={'rear': -1}),
    lambda d: d.update(notches={'front': 101}),
    lambda d: d.update(source='snapshot'),
    lambda d: d.update(extra=1),
    lambda d: d.pop('ball_housing'),
])
def test_invalid_document_rejected(mutation):
    data = to_data(make_inner())
    mutation(data)
    with pytest.raises(FreeArmInnerHousingFileError):
        from_data(data)
