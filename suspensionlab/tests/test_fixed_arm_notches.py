"""Временный формат подрезки не угадывает параметры и не меняет старые версии."""
from copy import deepcopy

import pytest
from test_fixed_arm_housings import housings

from suspensionlab.model.fixed_arm_housings import HousingError, make_housing_preview, validate_housing_preview
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, fixed_arm_tube_document
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize('values', [{}, {'front': -0.1}, {'front': 101}, {'front': True},
                                     {'front': float('nan')}, {'front': float('inf')},
                                     {'unknown': 0}, {'front': '0'}])
def test_invalid_selection_and_clearance(values):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2)
    with pytest.raises(HousingError):
        make_housing_preview(tubes, housings(), values)


def test_snapshot_validates_and_copies_selection():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2)
    plain = make_housing_preview(tubes, housings())
    assert plain['version'] == '1' and 'notches' not in plain
    selections = {'front': 0, 'rear': 2.5}
    doc = make_housing_preview(tubes, housings(), selections)
    selections['front'] = 8
    assert doc['version'] == '2' and doc['notches'] == {'front': 0, 'rear': 2.5}
    invalid = deepcopy(doc)
    invalid['notches']['front'] = -1
    with pytest.raises(HousingError):
        validate_housing_preview(invalid)
    invalid = deepcopy(doc)
    invalid['version'] = '1'
    with pytest.raises(HousingError):
        validate_housing_preview(invalid)
