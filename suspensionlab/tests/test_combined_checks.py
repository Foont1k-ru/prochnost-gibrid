"""Проверка заданных упоров в положении, использованном стабилизатором."""
from dataclasses import replace
from math import dist

import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
from suspensionlab.core.combined_checks import ComponentCheckOptions, check_components
from suspensionlab.core.pose_view import pose_view
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("travel", [-20, 0, 20])
def test_component_checks_match_independent_corner_analysis(side, travel):
    project = load_template("ring")
    axle = project.front
    system = AntiRollStudy(axle, AntiRollScenario(-250, 320, 1000))
    point = system.sweep([(travel, travel)]).points[0]
    arm = system.left if side == "left" else system.right
    pose = point.left_pose if side == "left" else point.right_pose
    assert pose is not None
    static = pose_view(arm.model, arm.model.initial_pose(), axle, spring=True, damper=True)
    current = pose_view(arm.model, pose, axle, spring=True, damper=True)
    limits = StrokeLimits(350, 450)
    result = check_components(current, static, ComponentCheckOptions(230, 150, limits))
    sample = analyze_corner(axle, project.vehicle, [travel], side=side, spring_mount="lower_arm",
                            static_spring_length_mm=230, coil_bind_length_mm=150,
                            damper_mount="lower_arm", damper_limits=limits).samples[0]
    assert sample is not None and sample.spring is not None and sample.spring.state is not None and sample.damper is not None
    assert result.spring is not None and result.damper is not None
    assert result.spring.length_mm == pytest.approx(sample.spring.state.length_mm, abs=1e-7)
    assert result.spring.coil_clearance_mm == pytest.approx(sample.spring.state.coil_clearance_mm, abs=1e-7)
    assert result.damper.length_mm == pytest.approx(sample.damper.length_mm, abs=1e-7)
    assert result.damper.stroke == sample.damper.stroke
    assert result.spring.status == "clear"


def test_unknown_inputs_and_boundaries_are_distinct():
    axle = load_template("ring").front
    system = AntiRollStudy(axle, AntiRollScenario(-250, 320, 1000))
    frame = pose_view(system.left.model, system.left.model.initial_pose(), axle, spring=True, damper=True)
    unknown = check_components(frame, frame, ComponentCheckOptions())
    assert unknown.spring is not None and unknown.spring.status == "length_unknown"
    assert unknown.damper is not None and unknown.damper.stroke is None
    partial = check_components(frame, frame, ComponentCheckOptions(230))
    assert partial.spring is not None and partial.spring.status == "limit_unknown"
    assert partial.spring.length_mm == 230
    assert frame.damper is not None
    length = dist(*frame.damper)
    conflict = check_components(frame, frame, ComponentCheckOptions(230, 230, StrokeLimits(length, length + 50)))
    assert conflict.spring is not None and conflict.spring.status == "coil_bind"
    assert conflict.damper is not None and conflict.damper.stroke is not None
    assert conflict.damper.stroke.status == "compressed_limit"
    missing = replace(frame, spring=None, damper=None)
    assert check_components(missing, frame, ComponentCheckOptions()) == check_components(missing, missing, ComponentCheckOptions())
    with pytest.raises(ValueError):
        ComponentCheckOptions(coil_bind_length_mm=100)
    with pytest.raises(ValueError):
        ComponentCheckOptions(static_spring_length_mm=float("nan"))


def test_coincident_mounts_are_invalid_not_a_success():
    axle = load_template("ring").front
    system = AntiRollStudy(axle, AntiRollScenario(-250, 320, 1000))
    frame = pose_view(system.left.model, system.left.model.initial_pose(), axle, spring=True, damper=True)
    assert frame.spring is not None and frame.damper is not None
    collapsed = replace(frame, spring=(frame.spring[0], frame.spring[0]), damper=(frame.damper[0], frame.damper[0]))
    result = check_components(collapsed, frame, ComponentCheckOptions(230, 150, StrokeLimits(300, 500)))
    assert result.spring is not None and result.spring.status == "invalid"
    assert result.damper is not None and result.damper.invalid
