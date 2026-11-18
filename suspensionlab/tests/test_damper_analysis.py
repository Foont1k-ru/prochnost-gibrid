"""Явно заданная кинематика и механические пределы амортизатора."""
import math

import numpy as np
import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.axle_analysis import analyze_symmetric_axle
from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.spring_characteristics import BumpStopCharacteristic
from suspensionlab.core.springs import lower_arm_spring_length
from suspensionlab.core.stroke import StrokeLimits, locate_lower_arm_length
from suspensionlab.model.templates import load_template


def test_damper_length_ratio_and_symmetry() -> None:
    project = load_template("ring")
    axle = project.front
    left = analyze_corner(axle, project.vehicle, [-20, 0, 20], damper_mount="lower_arm")
    right = analyze_corner(axle, project.vehicle, [-20, 0, 20], side="right", damper_mount="lower_arm")
    assert "damper_limits_unspecified" in left.limitations
    for a, b in zip(left.samples, right.samples, strict=True):
        assert a is not None and b is not None and a.damper is not None and b.damper is not None
        assert a.damper.length_mm == pytest.approx(b.damper.length_mm, abs=1e-7)
        assert a.damper.compression_from_static_mm == pytest.approx(b.damper.compression_from_static_mm, abs=1e-7)
        assert a.damper.motion_ratio == pytest.approx(b.damper.motion_ratio, abs=1e-7)
        assert a.damper.stroke is None
    assert left.samples[1] is not None and left.samples[1].damper is not None
    assert left.samples[1].damper.compression_from_static_mm == pytest.approx(0, abs=1e-9)
    plus, minus = analyze_corner(axle, project.vehicle, [9.99, 10.01], damper_mount="lower_arm").samples
    middle = analyze_corner(axle, project.vehicle, [10], damper_mount="lower_arm").samples[0]
    assert plus is not None and minus is not None and middle is not None
    assert plus.damper is not None and minus.damper is not None and middle.damper is not None
    assert middle.damper.motion_ratio == pytest.approx((plus.damper.length_mm - minus.damper.length_mm) / 0.02, abs=1e-7)


def test_damper_limits_report_conflict_without_faking_total_force() -> None:
    project = load_template("ring")
    model = DoubleWishbone(project.front)
    lower = np.array(project.front.hardpoints["damper_lo"].as_tuple())
    upper = np.array(project.front.hardpoints["damper_up"].as_tuple())
    length0 = lower_arm_spring_length(model, model.initial_pose(), lower, upper)
    limits = StrokeLimits(length0 - 5, length0 + 5)
    result = analyze_corner(project.front, project.vehicle, [-30, 0, 30], spring_mount="lower_arm",
                            static_spring_length_mm=230, bump_stop=BumpStopCharacteristic(100, 400, 0.5, 10),
                            damper_mount="lower_arm", damper_limits=limits)
    droop, static, bump = result.samples
    assert droop is not None and droop.damper is not None and droop.damper.stroke is not None
    assert static is not None and static.damper is not None and static.damper.stroke is not None
    assert bump is not None and bump.damper is not None and bump.damper.stroke is not None
    assert droop.damper.stroke.status == "above_extended"
    assert static.damper.stroke.status == "inside"
    assert bump.damper.stroke.status == "below_compressed"
    assert droop.damper.stroke.extension_clearance_mm < 0
    assert bump.damper.stroke.compression_clearance_mm < 0
    assert static.total_support_n is not None and droop.total_support_n is None and bump.total_support_n is None
    assert static.spring is not None and static.spring.frequency_hz is not None
    assert droop.spring is not None and droop.spring.frequency_hz is None
    assert bump.spring is not None and bump.spring.frequency_hz is None
    assert "damper_limits_discrete_only" in result.limitations
    # Кинематика остаётся доступной, но не является доказательством реального движения за упором.
    assert all(point.pose is not None for point in result.sweep.points)
    crossing = locate_lower_arm_length(model, tuple(lower), tuple(upper), limits.compressed_mm, 0, 30)
    assert 0 < crossing.estimated_travel_mm < 30


def test_exact_damper_stop_suppresses_frequency_and_sum() -> None:
    project = load_template("ring")
    model = DoubleWishbone(project.front)
    lower = np.array(project.front.hardpoints["damper_lo"].as_tuple())
    upper = np.array(project.front.hardpoints["damper_up"].as_tuple())
    length = lower_arm_spring_length(model, model.initial_pose(), lower, upper)
    point = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm", static_spring_length_mm=230,
                           bump_stop=BumpStopCharacteristic(100, 100, 1), damper_mount="lower_arm",
                           damper_limits=StrokeLimits(length, length + 10)).samples[0]
    assert point is not None and point.damper is not None and point.damper.stroke is not None
    assert point.damper.stroke.status == "compressed_limit"
    assert point.spring is not None and point.spring.frequency_hz is None and point.total_support_n is None


def test_symmetric_axle_forwards_all_explicit_scenarios() -> None:
    project = load_template("ring")
    result = analyze_symmetric_axle(project.front, project.vehicle, [0, 20], spring_mount="lower_arm",
                                    static_spring_length_mm=230, coil_bind_length_mm=150,
                                    bump_stop=BumpStopCharacteristic(10, 100, 0.5, 50),
                                    damper_mount="lower_arm", damper_limits=StrokeLimits(300, 500))
    for left, right in zip(result.left.samples, result.right.samples, strict=True):
        assert left is not None and right is not None
        assert left.spring is not None and right.spring is not None
        assert left.spring.state is not None and right.spring.state is not None
        assert left.spring.state.length_mm == pytest.approx(right.spring.state.length_mm)
        assert left.bump_stop is not None and right.bump_stop is not None
        assert left.bump_stop.wheel_force_n == pytest.approx(right.bump_stop.wheel_force_n)
        assert left.damper is not None and right.damper is not None
        assert left.damper.stroke is not None and right.damper.stroke is not None
        assert left.damper.length_mm == pytest.approx(right.damper.length_mm)
        assert left.total_support_n == pytest.approx(right.total_support_n)


def test_missing_mount_and_invalid_damper_geometry() -> None:
    project = load_template("ring")
    plain = analyze_corner(project.front, project.vehicle, [0])
    assert plain.samples[0] is not None and plain.samples[0].damper is None
    assert "damper_mount_unspecified" in plain.limitations
    with pytest.raises(ValueError, match="крепление"):
        analyze_corner(project.front, project.vehicle, [0], damper_limits=StrokeLimits(200, 500))
    del project.front.hardpoints["damper_lo"]
    with pytest.raises(ValueError, match="опоры амортизатора"):
        analyze_corner(project.front, project.vehicle, [0], damper_mount="lower_arm")
    project = load_template("ring")
    project.front.hardpoints["damper_lo"].x = math.nan
    with pytest.raises(ValueError, match="конечными"):
        analyze_corner(project.front, project.vehicle, [0], damper_mount="lower_arm")
    project = load_template("ring")
    a, b = project.front.hardpoints["damper_lo"], project.front.hardpoints["damper_up"]
    a.x, a.y, a.z = b.x, b.y, b.z
    with pytest.raises(ValueError, match="совпадают"):
        analyze_corner(project.front, project.vehicle, [0], damper_mount="lower_arm")
