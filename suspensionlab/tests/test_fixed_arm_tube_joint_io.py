"""Рецепт подрезки по трубе сохраняется только с корректным снимком."""
import json
from copy import deepcopy

import pytest
from test_fixed_arm_housings import housings

from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm
from suspensionlab.model.fixed_arm_skeleton_io import SkeletonFileError, read_skeleton, write_skeleton
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize('with_housings', [False, True])
def test_roundtrip_and_exact_source_match(tmp_path, with_housings):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    housing = housings() if with_housings else None
    notches = {'front': 1.0} if with_housings else None
    joint = {'target': 'rear', 'radial_clearance_mm': 0.75}
    path = tmp_path / 'joint.slarm'
    write_skeleton(path, snapshot, project, 10, 2, {}, housing, notches, joint)
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['version'] == '4'
    loaded = read_skeleton(path, project)
    assert loaded.tube_joint == joint and loaded.housings == housing and loaded.notches == notches
    original = deepcopy(data)
    for mutate in (lambda d: d['geometry']['tube_joint'].update(target='both'),
                   lambda d: d['geometry']['tube_joint'].update(radial_clearance_mm=-1),
                   lambda d: d['geometry']['tube_joint'].update(radial_clearance_mm=True),
                   lambda d: d['geometry'].pop('tube_joint'),
                   lambda d: d.update(version='3')):
        data = deepcopy(original)
        mutate(data)
        path.write_text(json.dumps(data), encoding='utf-8')
        with pytest.raises(SkeletonFileError):
            read_skeleton(path, project)
    path.write_text(json.dumps(original), encoding='utf-8')
    project.front.hardpoints['lbj'].x += 0.000001
    with pytest.raises(SkeletonFileError):
        read_skeleton(path, project)
