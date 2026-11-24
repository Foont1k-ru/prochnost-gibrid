"""Независимая односторонняя подрезка: параметры и версии .slarm."""
from copy import deepcopy

import pytest
from test_free_arm_housing_io import make_draft
from test_free_arm_inner_housings import make_inner

from suspensionlab.model.free_arm_housing_io import from_data as read_v2
from suspensionlab.model.free_arm_housing_io import read_independent_arm
from suspensionlab.model.free_arm_inner_housings_io import from_data as read_v3
from suspensionlab.model.free_arm_io import from_data as read_v1
from suspensionlab.model.free_arm_miter_io import from_data as read_v4
from suspensionlab.model.free_arm_tube_joint import FreeArmTubeJoint, FreeArmTubeJointDraft
from suspensionlab.model.free_arm_tube_joint_io import (
    FreeArmTubeJointFileError,
    from_data,
    to_data,
    write_free_arm_tube_joint,
)


@pytest.mark.parametrize('leg', ['front', 'rear'])
@pytest.mark.parametrize('inner', [False, True])
def test_roundtrip_and_all_old_readers_reject(tmp_path, leg, inner):
    base = make_inner(bent=('front',))
    draft = FreeArmTubeJointDraft(base.arm, FreeArmTubeJoint(leg, 1.25), base.housings if inner else None)
    data = to_data(draft)
    before = deepcopy(data)
    assert data['version'] == '5' and data['source'] == 'independent'
    assert from_data(data) == draft and data == before
    for reader in (read_v1, read_v2, read_v3, read_v4):
        with pytest.raises(ValueError):
            reader(data)
    path = write_free_arm_tube_joint(tmp_path / 'joint.slarm', draft)
    assert read_independent_arm(path) == draft
    with pytest.raises(FreeArmTubeJointFileError):
        write_free_arm_tube_joint(path, draft)
    assert read_independent_arm(path) == draft


@pytest.mark.parametrize('mutation', [
    lambda d: d['joint'].update(target='miter'),
    lambda d: d['joint'].update(target='both'),
    lambda d: d['joint'].update(radial_clearance_mm=-1),
    lambda d: d['joint'].update(radial_clearance_mm=101),
    lambda d: d['joint'].update(radial_clearance_mm=True),
    lambda d: d['joint'].update(radial_clearance_mm=float('nan')),
    lambda d: d['joint'].update(extra=0),
    lambda d: d.update(notches={'front': 0}),
    lambda d: d.update(ball_housing={}),
    lambda d: d.update(source='snapshot'),
    lambda d: d.update(extra=0),
    lambda d: d.pop('joint'),
])
def test_rejects_invalid_or_incompatible_data(mutation):
    doc = to_data(FreeArmTubeJointDraft(make_draft().arm, FreeArmTubeJoint('front', 0)))
    mutation(doc)
    with pytest.raises(FreeArmTubeJointFileError):
        from_data(doc)
