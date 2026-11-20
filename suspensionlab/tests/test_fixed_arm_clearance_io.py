"""Только явно заданные минимумы сохраняются; геометрические результаты — нет."""
import json
from copy import deepcopy

import pytest
from test_fixed_arm_housings import housings

from suspensionlab.model.fixed_arm_clearances import validate_requirements
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm
from suspensionlab.model.fixed_arm_skeleton_io import SkeletonFileError, read_skeleton, write_skeleton
from suspensionlab.model.templates import load_template


def test_roundtrip_v5_and_old_files_unchanged(tmp_path):
    project = load_template('ring')
    before = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20)
    for i, (h, req) in enumerate(((None, {'tube_front|tube_rear': 0}),
                                   (housings(), {'tube_front|tube_rear': 1.2, 'tube_front|housing_front': 0.5}))):
        path = tmp_path / f'{i}.slarm'
        write_skeleton(path, snapshot, project, 10, 2, {}, h, None, None, req)
        data = json.loads(path.read_text(encoding='utf-8'))
        assert data['version'] == '5' and data['geometry']['clearance_requirements_mm'] == req
        assert 'pairs' not in data and 'result' not in data['geometry']
        loaded = read_skeleton(path, project)
        assert loaded.clearance_requirements == req
    legacy = tmp_path / 'legacy.slarm'
    write_skeleton(legacy, snapshot, project, 10, 2, {})
    assert json.loads(legacy.read_text(encoding='utf-8'))['version'] == '1'
    assert read_skeleton(legacy, project).clearance_requirements is None
    assert project.to_dict() == before


@pytest.mark.parametrize('bad', [None, [], {'unknown|pair': 0}, {'tube_rear|tube_front': 1},
                                  {'tube_front|tube_rear': True}, {'tube_front|tube_rear': -1},
                                  {'tube_front|tube_rear': 0.000001}, {'tube_front|tube_rear': float('nan')},
                                  {'tube_front|tube_rear': 101}, {'tube_front|housing_front': 1}])
def test_bad_requirements_rejected(bad):
    with pytest.raises(ValueError):
        validate_requirements(bad, housings=False)


def test_corrupted_v5_fails_without_filling_defaults(tmp_path):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    path = tmp_path / 'file.slarm'
    write_skeleton(path, snapshot, project, 10, 2, {}, clearance_requirements={'tube_front|tube_rear': 1})
    data = json.loads(path.read_text(encoding='utf-8'))
    for mutation in (lambda d: d['geometry'].pop('tube_joint'),
                     lambda d: d['geometry'].update(clearance_requirements_mm={}),
                     lambda d: d['geometry'].update(clearance_requirements_mm={'tube_front|housing_front': 1}),
                     lambda d: d['geometry'].update(clearance_requirements_mm={'tube_front|tube_rear': '1'})):
        altered = deepcopy(data)
        mutation(altered)
        path.write_text(json.dumps(altered), encoding='utf-8')
        with pytest.raises(SkeletonFileError):
            read_skeleton(path, project)


@pytest.mark.parametrize(('h', 'notches', 'joint'), [
    (None, None, None), (None, None, {'target': 'rear', 'radial_clearance_mm': 0.5}),
    (housings(), None, None), (housings(), {'front': 1}, None),
    (housings(), {'rear': 0}, {'target': 'front', 'radial_clearance_mm': 2}),
])
def test_v5_preserves_optional_geometry_without_assumptions(tmp_path, h, notches, joint):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    path = tmp_path / 'geometry.slarm'
    req = {'tube_front|tube_rear': .5}
    write_skeleton(path, snapshot, project, 10, 2, {}, h, notches, joint, req)
    loaded = read_skeleton(path, project)
    assert loaded.housings == h and loaded.notches == notches and loaded.tube_joint == joint
    assert loaded.clearance_requirements == req
