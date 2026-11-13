"""Отдельная идеализированная модель стабилизатора и жёстких стоек."""
import math

import numpy as np
import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
from suspensionlab.core.sweep import travel_grid
from suspensionlab.model.templates import load_template


def study(rate: float = 1000) -> AntiRollStudy:
    return AntiRollStudy(load_template("ring").front, AntiRollScenario(-250, 320, rate))


def point(system: AntiRollStudy, left: float, right: float):
    result = system.sweep([(left, right)])
    assert result.points[0].error is None and result.points[0].state is not None
    return result.points[0].state


def test_small_grid_tracks_spring_damper_and_antiroll_links() -> None:
    project = load_template("ring")
    grid = travel_grid(-20, 20)
    result = analyze_corner(project.front, project.vehicle, grid, spring_mount="lower_arm",
                            static_spring_length_mm=230, damper_mount="lower_arm")
    bar = study().sweep_travel(-20, 20)
    assert len(result.samples) == len(bar.points) == 41
    for spring, antiroll in zip(result.samples, bar.points, strict=True):
        assert spring is not None and spring.spring is not None and spring.spring.state is not None
        assert spring.damper is not None and spring.damper.motion_ratio is not None
        assert antiroll.state is not None
        assert antiroll.state.left_travel_mm == pytest.approx(spring.pose.travel_mm)
    assert "sampled_path_not_continuously_verified" in bar.limitations
    bounce = study().sweep_travel(-2, 2, mode="bounce", step_mm=0.25)
    assert len(bounce.points) == 17
    assert all(p.state is not None and abs(p.state.torque_nm) < 1e-8 for p in bounce.points)


def test_equal_bump_no_twist_and_unequal_motion_loads_both_links() -> None:
    system = study()
    bounce = point(system, 20, 20)
    assert bounce.twist_deg == pytest.approx(0, abs=1e-8)
    assert bounce.torque_nm == pytest.approx(0, abs=1e-8)
    assert bounce.left.compression_force_n == pytest.approx(0, abs=1e-6)
    assert bounce.left.arm_angle_deg == pytest.approx(bounce.right.arm_angle_deg, abs=1e-8)
    anti = point(system, 10, -10)
    assert abs(anti.twist_deg) > 1 and abs(anti.torque_nm) > 1
    assert anti.left.compression_force_n > 0 and anti.right.compression_force_n < 0
    assert anti.left.wheel_resistance_n > 0 and anti.right.wheel_resistance_n < 0
    swapped = point(system, -10, 10)
    assert swapped.twist_deg == pytest.approx(-anti.twist_deg, abs=1e-8)
    assert swapped.left.compression_force_n == pytest.approx(anti.right.compression_force_n, abs=1e-7)
    assert swapped.left.lower_mm == pytest.approx((anti.right.lower_mm[0], -anti.right.lower_mm[1], anti.right.lower_mm[2]))


def test_virtual_work_moment_balance_and_rigid_links() -> None:
    system = study()
    center = point(system, 12, -8)
    delta = 0.001
    left_low, left_high = point(system, 12 - delta, -8), point(system, 12 + delta, -8)
    right_low, right_high = point(system, 12, -8 - delta), point(system, 12, -8 + delta)
    # Дж/мм -> Н: dE/dh * 1000.
    assert center.left.wheel_resistance_n == pytest.approx(
        (left_high.strain_energy_j - left_low.strain_energy_j) / (2 * delta) * 1000, rel=2e-6)
    assert center.right.wheel_resistance_n == pytest.approx(
        (right_high.strain_energy_j - right_low.strain_energy_j) / (2 * delta) * 1000, rel=2e-6)
    for link, sign in ((center.left, 1), (center.right, -1)):
        lower, upper = np.array(link.lower_mm), np.array(link.upper_mm)
        assert link.length_mm == pytest.approx(np.linalg.norm(upper - lower), abs=1e-10)
        initial = point(system, 0, 0).left.length_mm
        assert link.length_mm == pytest.approx(initial, abs=1e-6)
        moment_arm = np.dot((upper - lower) / link.length_mm, np.cross([0, 1, 0], upper - system.origin))
        assert link.compression_force_n * moment_arm == pytest.approx(sign * center.torque_nm * 1000, abs=1e-7)


def test_zero_stiffness_and_invalid_geometry_are_explicit() -> None:
    relaxed = point(study(0), 20, -20)
    assert relaxed.twist_deg != 0 and relaxed.torque_nm == 0
    assert relaxed.left.compression_force_n == 0 and relaxed.right.wheel_resistance_n == 0
    for value in (-1, math.nan, math.inf):
        with pytest.raises(ValueError):
            AntiRollScenario(0, 0, value)
    with pytest.raises(ValueError):
        AntiRollScenario(0, 0, 100, max_angle_step_deg=90)
    axle = load_template("ring").front
    with pytest.raises(ValueError, match="на оси"):
        AntiRollStudy(axle, AntiRollScenario(axle.hardpoints["arb_up"].x, axle.hardpoints["arb_up"].z, 100))
    del axle.hardpoints["arb_lo"]
    with pytest.raises(ValueError, match="опоры"):
        AntiRollStudy(axle, AntiRollScenario(0, 0, 100))


def test_failure_keeps_prefix_and_does_not_guess_later_points() -> None:
    system = study()
    result = system.sweep([(0, 0), (10, -10), (2000, -2000), (0, 0)])
    assert result.points[0].state is not None and result.points[1].state is not None
    assert result.points[2].state is None and result.points[2].error is not None
    assert result.points[3].state is None and result.points[3].error == result.points[2].error
    with pytest.raises(ValueError):
        system.sweep([(0, 0)], max_step_mm=0)
    with pytest.raises(ValueError):
        system.sweep([(math.nan, 0)])
    with pytest.raises(ValueError, match="много шагов"):
        system.sweep([(100, -100)], max_step_mm=0.001)


def test_dense_demo_prints_displacements_and_forces(capsys: pytest.CaptureFixture[str]) -> None:
    from examples.dense_sweep_demo import main

    main()
    text = capsys.readouterr().out
    assert "УЧЕБНЫЙ ПРИМЕР" in text
    assert "Угол плеча" in text and "Сжатие стоек" in text
    assert "-30.0/+30.0" in text and "+35.0/-35.0" in text
    assert "нет результата" not in text
