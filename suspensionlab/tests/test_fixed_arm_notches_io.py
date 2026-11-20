"""Сохраняются параметры подрезки, а не доверенный результат CAD."""
import json
from copy import deepcopy

import pytest
from test_fixed_arm_housings import housings

from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm
from suspensionlab.model.fixed_arm_skeleton_io import SkeletonFileError, read_skeleton, write_skeleton
from suspensionlab.model.templates import load_template


def test_roundtrip_and_project_mismatch(tmp_path):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    selected = {'front': 0.0, 'rear': 1.125}
    path = tmp_path / 'notches.slarm'
    write_skeleton(path, snapshot, project, 10, 2, {}, housings(), selected)
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['version'] == '3' and data['geometry']['notches'] == selected
    result = read_skeleton(path, project)
    assert result.notches == selected and result.housings == housings()
    project.front.hardpoints['lbj'].x += 0.000001
    with pytest.raises(SkeletonFileError):
        read_skeleton(path, project)


def test_tampering_and_missing_housing_rejected(tmp_path):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    path = tmp_path / 'notches.slarm'
    write_skeleton(path, snapshot, project, 10, 2, {}, housings(), {'front': 0})
    original = json.loads(path.read_text(encoding='utf-8'))
    for mutation in (lambda d: d['geometry'].update(notches={}),
                     lambda d: d['geometry'].update(notches={'front': -1}),
                     lambda d: d['geometry'].update(notches={'rear': True}),
                     lambda d: d['geometry'].pop('housings'),
                     lambda d: d.update(version='2')):
        altered = deepcopy(original)
        mutation(altered)
        path.write_text(json.dumps(altered), encoding='utf-8')
        with pytest.raises(SkeletonFileError):
            read_skeleton(path, project)
    with pytest.raises(SkeletonFileError):
        write_skeleton(tmp_path / 'bad.slarm', snapshot, project, 10, 2, {}, None, {'front': 0})
