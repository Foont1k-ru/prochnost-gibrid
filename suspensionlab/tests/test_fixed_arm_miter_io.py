"""Версии общего стыка: старые файлы не получают новое значение скрыто."""
import json
from copy import deepcopy

import pytest

from suspensionlab.model.fixed_arm_housings import HousingError, make_housing_preview, validate_housing_preview
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, fixed_arm_tube_document
from suspensionlab.model.fixed_arm_skeleton_io import SkeletonFileError, read_skeleton, write_skeleton
from suspensionlab.model.templates import load_template


def test_miter_preview_and_skeleton_roundtrip(tmp_path):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2)
    joint = {'target': 'miter', 'radial_clearance_mm': 0.}
    preview = make_housing_preview(tubes, None, tube_joint=joint)
    assert preview['version'] == '4'
    validate_housing_preview(preview)
    invalid = deepcopy(preview)
    invalid['version'] = '3'
    with pytest.raises(HousingError):
        validate_housing_preview(invalid)
    invalid = deepcopy(preview)
    invalid['tube_joint']['radial_clearance_mm'] = .1
    with pytest.raises(HousingError):
        validate_housing_preview(invalid)
    path = tmp_path / 'miter.slarm'
    write_skeleton(path, snapshot, project, 10, 2, {}, tube_joint=joint)
    content = json.loads(path.read_text(encoding='utf-8'))
    assert content['version'] == '6'
    assert read_skeleton(path, project).tube_joint == joint
    content['version'] = '5'
    content['geometry']['clearance_requirements_mm'] = {'tube_front|tube_rear': 0.}
    path.write_text(json.dumps(content), encoding='utf-8')
    with pytest.raises(SkeletonFileError):
        read_skeleton(path, project)


def test_bad_miter_geometry_not_saved(tmp_path):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, 0, 0)
    path = tmp_path / 'bad.slarm'
    with pytest.raises(SkeletonFileError):
        write_skeleton(path, snapshot, project, 200, 2, {},
                       tube_joint={'target': 'miter', 'radial_clearance_mm': 0.})
    assert not path.exists()
