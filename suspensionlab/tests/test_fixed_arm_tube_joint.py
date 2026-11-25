"""Одна явно выбранная подрезаемая ветвь и строго проверяемый временный формат."""
from copy import deepcopy

import pytest
from test_fixed_arm_housings import housings

from suspensionlab.model.fixed_arm_housings import (
    HousingError,
    make_housing_preview,
    validate_housing_preview,
    validate_tube_joint,
)
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, fixed_arm_tube_document
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize('value', [None, {}, {'target': 'both', 'radial_clearance_mm': 0},
                                   {'target': 'front', 'radial_clearance_mm': True},
                                   {'target': 'rear', 'radial_clearance_mm': -1},
                                   {'target': 'rear', 'radial_clearance_mm': 101},
                                   {'target': 'front', 'radial_clearance_mm': float('nan')},
                                   {'target': 'front', 'radial_clearance_mm': '0'},
                                   {'target': 'front', 'radial_clearance_mm': 0, 'extra': 1}])
def test_invalid_joint_rejected(value):
    with pytest.raises(HousingError):
        validate_tube_joint(value)


def test_detached_and_v1_v2_compatible():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2)
    joint = {'target': 'rear', 'radial_clearance_mm': 0}
    doc = make_housing_preview(tubes, None, tube_joint=joint)
    assert doc['version'] == '3' and doc['housings'] is None and doc['notches'] is None
    joint['target'] = 'front'
    assert doc['tube_joint']['target'] == 'rear'
    doc2 = make_housing_preview(tubes, housings(), {'front': 1}, joint)
    assert doc2['notches'] == {'front': 1} and doc2['tube_joint']['target'] == 'front'
    assert make_housing_preview(tubes, housings())['version'] == '1'
    assert make_housing_preview(tubes, housings(), {'rear': 0})['version'] == '2'
    tampered = deepcopy(doc)
    tampered['notches'] = {'front': 0}
    with pytest.raises(HousingError):
        validate_housing_preview(tampered)
    tampered = deepcopy(doc2)
    tampered['tube_joint']['target'] = 'both'
    with pytest.raises(HousingError):
        validate_housing_preview(tampered)
