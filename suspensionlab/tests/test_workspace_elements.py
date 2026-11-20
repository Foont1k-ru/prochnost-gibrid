"""Явные крепления, пределы и отсутствие ложных проверок."""
from dataclasses import replace
from math import dist

import numpy as np
import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.kinematics_workspace import calculate, measure_element
from suspensionlab.core.rear_five_link import RearFiveLink
from suspensionlab.core.springs import lower_arm_point
from suspensionlab.model.entities import Project
from suspensionlab.model.kinematic_elements import ElementSetup, KinematicElements
from suspensionlab.model.templates import load_template


def test_unknown_and_explicit_attachment_trajectory_and_limits():
    axle = load_template('ring').front
    assert axle.kinematic_elements is None
    unknown = calculate(axle, 0, 20, 10)
    assert all(s.spring.status == 'unknown' and s.damper.status == 'unknown' for s in unknown.samples)
    setup = ElementSetup('lower_arm', 'body')
    axle.kinematic_elements = KinematicElements(axle.type_code, setup, ElementSetup('upright', 'body'))
    result = calculate(axle, 0, 20, 10)
    model = DoubleWishbone(axle)
    pose = model.solve(20)
    sample = result.samples[-1]
    lower = np.array(axle.hardpoints['spring_lo'].as_tuple())
    upper = axle.hardpoints['spring_up'].as_tuple()
    expected = lower_arm_point(model, pose, lower)
    assert sample.spring.lower == pytest.approx(expected)
    assert sample.spring.length_mm == pytest.approx(dist(expected, upper))
    assert sample.spring.status == 'partial'
    assert sample.scene.point('spring_lo') == pytest.approx(expected)
    assert sample.damper.lower == pytest.approx(pose.point(np.array(axle.hardpoints['damper_lo'].as_tuple()), model.center0))
    length = sample.spring.length_mm
    for min_, max_, status in [(None, length - 1, 'above'), (length + 1, None, 'below'),
                                (length, length + 1, 'limit'), (length - 1, length + 1, 'inside'),
                                (length + 1, length - 1, 'invalid')]:
        axle.kinematic_elements = replace(axle.kinematic_elements, spring=replace(setup, minimum_mm=min_, maximum_mm=max_))
        assert measure_element(axle, model, pose, 'spring').status == status


def test_rear_upright_and_corrupt_or_missing_data():
    axle = load_template('ring').rear
    model = RearFiveLink(axle)
    pose = model.solve(20)
    axle.kinematic_elements = KinematicElements(axle.type_code, ElementSetup('upright', 'body'))
    result = measure_element(axle, model, pose, 'spring')
    assert result.lower == pytest.approx(pose.point(np.array(axle.hardpoints['spring_lo'].as_tuple()), model.center0))
    assert result.upper == pytest.approx(axle.hardpoints['spring_up'].as_tuple())
    with pytest.raises(ValueError):
        KinematicElements(axle.type_code, ElementSetup('lower_arm', 'body'))
    del axle.hardpoints['spring_lo']
    assert measure_element(axle, model, pose, 'spring').status == 'error'
    for value in (float('nan'), float('inf'), -1, True):
        with pytest.raises(ValueError):
            ElementSetup(minimum_mm=value)


def test_roundtrip_optional_config_and_malformed_input_rejected():
    project = load_template('ring')
    original = project.to_dict()
    assert 'kinematic_elements' not in original['front_axle']
    assert Project.from_dict(original).to_dict() == original
    project.front.kinematic_elements = KinematicElements('double_wishbone', ElementSetup('lower_arm', 'body', 100, 500))
    saved = project.to_dict()
    assert Project.from_dict(saved).to_dict() == saved
    saved['front_axle']['kinematic_elements']['spring']['minimum_mm'] = 'not a number'
    with pytest.raises(ValueError):
        Project.from_dict(saved)
