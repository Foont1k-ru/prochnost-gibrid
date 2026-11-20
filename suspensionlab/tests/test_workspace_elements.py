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


def _rocker_setup(axle, code, *, enabled=True, mount='upright'):
    from suspensionlab.model.kinematic_elements import RockerSetup

    bx, by, bz = axle.hardpoints[code].as_tuple()
    x, y, z = bx + 30., by - 20., bz + 10.
    return RockerSetup(enabled, mount, (x + 100, y + 20, z + 100), (1, 0, 0),
                       (x + 100, y + 70, z + 100), (x, y, z),
                       (x + 100, y + 20, z + 130), (x + 100, y + 100, z + 160))


def test_saved_rocker_and_direct_mode_roundtrip_and_invalid_input():
    from suspensionlab.model.kinematic_elements import RockerSetup

    project = load_template('ring')
    rocker = _rocker_setup(project.front, 'lbj')
    config = KinematicElements('double_wishbone', ElementSetup('body', 'upright'),
                               ElementSetup('upright', 'body', 50., 200.), rocker)
    project.front.kinematic_elements = config
    saved = project.to_dict()
    import json
    decoded = Project.from_dict(json.loads(json.dumps(saved)))
    assert decoded.front.kinematic_elements == config
    assert decoded.to_dict() == saved
    data = config.to_dict()
    data['rocker']['pivot'] = [True, 0., 0.]
    with pytest.raises(ValueError):
        KinematicElements.from_dict(data)
    with pytest.raises(ValueError):
        KinematicElements('multilink_rear', rocker=replace(rocker, mount='lower_arm'))
    with pytest.raises(ValueError):
        replace(rocker, enabled='yes')
    with pytest.raises(ValueError):
        RockerSetup.from_dict({'enabled': True})


def test_active_rocker_replaces_direct_damper_without_stale_fallback():
    axle = load_template('ring').front
    rocker = _rocker_setup(axle, 'lbj', mount='lower_arm')
    direct = ElementSetup('upright', 'body', 20., 500.)
    axle.kinematic_elements = KinematicElements(axle.type_code, damper=direct, rocker=rocker)
    model = DoubleWishbone(axle)
    single = measure_element(axle, model, model.initial_pose(), 'damper')
    assert single.length_mm is None and single.status == 'unknown'
    result = calculate(axle, -27, 23, 9)
    assert len(result.samples) > 2
    assert all(s.scene is not None and s.rocker is not None and s.rocker.pose is not None for s in result.samples)
    for sample in result.samples:
        assert sample.damper.length_mm == pytest.approx(sample.rocker.pose.damper_length_mm)
        assert sample.damper.status == 'inside'
        assert {'rod', 'rocker', 'damper'} <= {seg.kind for seg in sample.scene.segments}
        assert sample.scene.point('damper_lo') is None
    assert all(s.rocker.motion_ratio is not None for s in result.samples[1:-1])
    axle.kinematic_elements = replace(axle.kinematic_elements, rocker=replace(rocker, enabled=False))
    direct_result = calculate(axle, -27, 23, 9)
    assert all(s.rocker is None for s in direct_result.samples)
    assert all(s.scene.point('damper_lo') is not None for s in direct_result.samples)
    assert abs(direct_result.samples[0].damper.length_mm - result.samples[0].damper.length_mm) > 1
    invalid = replace(rocker, axis=(0., 0., 0.))
    axle.kinematic_elements = replace(axle.kinematic_elements, rocker=invalid)
    failed = calculate(axle, -6, 6, 5)
    assert all(s.damper.status == 'error' and s.damper.length_mm is None for s in failed.samples)
    assert all(not any(seg.kind in ('damper', 'rod', 'rocker') for seg in s.scene.segments) for s in failed.samples)


def test_rear_rocker_and_unknown_force_ratio_are_separate_from_spring():
    axle = load_template('ring').rear
    rocker = _rocker_setup(axle, 'uf_out')
    axle.kinematic_elements = KinematicElements(axle.type_code, spring=ElementSetup('upright', 'body'), rocker=rocker)
    samples = calculate(axle, -6, 6, 5).samples
    assert all(s.rocker is not None and s.rocker.pose is not None for s in samples)
    assert all(s.spring.length_mm is not None for s in samples)
    assert all(s.damper.status == 'partial' for s in samples)
