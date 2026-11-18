"""Привод, знаки статической настройки и проекция мгновенного центра."""
from __future__ import annotations

import math

import numpy as np
import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.drivetrain import HalfshaftGeometry, halfshaft_metrics
from suspensionlab.core.geometry import intersect_lines_2d
from suspensionlab.core.metrics import corner_metrics
from suspensionlab.core.roll_center import projected_instant_center, symmetric_roll_center_height
from suspensionlab.model.templates import load_template


def _planar_solver(equal: bool = False) -> DoubleWishbone:
    axle = load_template("ring").front
    upper_y = 300 if equal else 380
    coords = {
        "uca_f_in": (100, upper_y, 400), "uca_r_in": (-100, upper_y, 400), "ubj": (0, 700, 400),
        "lca_f_in": (100, 300, 150), "lca_r_in": (-100, 300, 150), "lbj": (0, 700, 150),
        "tierod_in": (-150, 300, 200), "tierod_out": (-150, 700, 200), "wheel_center": (0, 750, 310),
    }
    for code, (x, y, z) in coords.items():
        point = axle.hardpoints[code]
        point.x, point.y, point.z = x, y, z
    return DoubleWishbone(axle)


def test_static_alignment_explicit_and_mirrored() -> None:
    axle = load_template("ring").front
    for side in ("left", "right"):
        model = DoubleWishbone(axle, side)
        m = corner_metrics(model, model.initial_pose(), static_camber_deg=-2.5, static_toe_deg=0.15)
        assert m.camber_deg == pytest.approx(-2.5, abs=1e-10)
        assert m.toe_deg == pytest.approx(0.15, abs=1e-10)
        with pytest.raises(ValueError):
            corner_metrics(model, model.initial_pose(), static_camber_deg=90)


def test_projected_ic_agrees_with_planar_analytical_case() -> None:
    solver = _planar_solver()
    pose = solver.solve(20)
    ic = projected_instant_center(solver, pose)
    ubj = pose.point(solver.points["ubj"], solver.center0)
    lbj = pose.point(solver.points["lbj"], solver.center0)
    expected = intersect_lines_2d(tuple(solver.points["uca_f_in"][1:]), tuple(ubj[1:]),
                                  tuple(solver.points["lca_f_in"][1:]), tuple(lbj[1:]))
    assert expected is not None and not ic.at_infinity
    assert (ic.y, ic.z) == pytest.approx(expected, abs=1e-5)
    expected_rc = intersect_lines_2d((pose.center[1], 0), expected, (0, -10000), (0, 10000))
    assert expected_rc is not None
    assert symmetric_roll_center_height(solver, pose) == pytest.approx(expected_rc[1], abs=1e-5)


def test_parallel_arms_ic_at_infinity_and_rc_on_ground() -> None:
    solver = _planar_solver(equal=True)
    pose = solver.initial_pose()
    ic = projected_instant_center(solver, pose)
    assert ic.at_infinity
    assert symmetric_roll_center_height(solver, pose) == pytest.approx(0, abs=1e-9)


def test_drivetrain_explicit_joint_angles_and_travel() -> None:
    axle = load_template("ring").front
    model = DoubleWishbone(axle)
    inner = (0.0, 100.0, 300.0)
    outer = (0.0, 700.0, 300.0)
    geometry = HalfshaftGeometry(inner, outer, (0, 1, 0), (0, 1, 0), 600, -10, 15)
    initial = halfshaft_metrics(model, model.initial_pose(), geometry)
    assert initial.length_mm == pytest.approx(600)
    assert initial.inner_angle_deg == pytest.approx(0)
    assert initial.outer_angle_deg == pytest.approx(0)
    assert initial.clearance_to_min_mm == pytest.approx(10)
    assert initial.clearance_to_max_mm == pytest.approx(15)
    pose = model.solve(30)
    current = halfshaft_metrics(model, pose, geometry)
    expected = pose.point(np.array(outer), model.center0) - inner
    assert current.length_mm == pytest.approx(np.linalg.norm(expected))
    assert current.inner_angle_deg == pytest.approx(math.degrees(math.acos(expected[1] / np.linalg.norm(expected))))
    assert current.plunge_mm == pytest.approx(current.length_mm - 600)


def test_invalid_drive_inputs() -> None:
    with pytest.raises(ValueError):
        HalfshaftGeometry((0, 0, 0), (0, 1, 0), (0, 0, 0), (0, 1, 0), 1, -1, 1)
    with pytest.raises(ValueError):
        HalfshaftGeometry((0, 0, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0), 1, 1, -1)


def test_included_angle_uses_spatial_axis_and_wheel_plane() -> None:
    model = _planar_solver()
    metrics = corner_metrics(model, model.initial_pose(), static_camber_deg=-2.0)
    assert metrics.included_angle_deg == pytest.approx(2.0)


def test_limited_sweep_returns_partial_branches() -> None:
    from suspensionlab.core.sweep import limited_sweep

    model = _planar_solver(equal=True)
    result = limited_sweep(model, [30, -20, 0, 500, -30, 550], max_step_mm=2)
    assert [p.travel_mm for p in result.points] == [30, -20, 0, 500, -30, 550]
    assert result.points[0].pose is not None
    assert result.points[1].pose is not None
    assert result.points[3].pose is None and result.points[3].error is not None
    assert result.points[5].error is result.points[3].error
    assert result.reachable_bump_mm >= 30
    assert result.reachable_droop_mm == pytest.approx(-30)


def test_mass_roll_stiffness_and_piecewise_spring() -> None:
    from suspensionlab.core.springs import (
        axle_roll_stiffness_nm_per_degree,
        progressive_spring_rate,
        sprung_mass_per_corner,
    )

    assert sprung_mass_per_corner(1400, 0.6, 40) == pytest.approx(380)
    assert axle_roll_stiffness_nm_per_degree(40, 1500) == pytest.approx(2 * 40 * 750**2 / 1000 * math.pi / 180)
    assert progressive_spring_rate([(0, 0), (10, 100), (20, 300)], 5) == pytest.approx(10)
    assert progressive_spring_rate([(0, 0), (10, 100), (20, 300)], 15) == pytest.approx(20)
    with pytest.raises(ValueError):
        progressive_spring_rate([(0, 0), (10, 100), (20, 300)], 10)
    with pytest.raises(ValueError):
        sprung_mass_per_corner(1000, 0.1, 100)


def test_analytic_spring_motion_ratio_matches_central_difference() -> None:
    from suspensionlab.core.springs import lower_arm_motion_ratio, lower_arm_motion_ratio_at_pose

    axle = load_template("ring").front
    model = DoubleWishbone(axle)
    lower = np.array(axle.hardpoints["spring_lo"].as_tuple())
    upper = np.array(axle.hardpoints["spring_up"].as_tuple())
    for travel in (-30, 0, 30):
        analytic = lower_arm_motion_ratio_at_pose(model, model.solve(travel), lower, upper)
        finite = lower_arm_motion_ratio(model, travel, lower, upper)
        assert analytic == pytest.approx(finite, abs=1e-7)


def test_partial_corner_analysis_uses_setup_and_explicit_spring_mount() -> None:
    from suspensionlab.core.analysis import analyze_corner

    project = load_template("ring")
    result = analyze_corner(project.front, project.vehicle, [-10, 0, 10], spring_mount="lower_arm")
    assert len(result.samples) == 3
    static = result.samples[1]
    assert static is not None and static.spring is not None
    assert static.geometry.camber_deg == pytest.approx(project.front.setup.camber_deg)
    assert static.geometry.toe_deg == pytest.approx(project.front.setup.toe_deg_total / 2)
    assert static.spring.motion_ratio > 0
    assert static.spring.frequency_hz is not None and static.spring.frequency_hz > 0
    assert static.spring.state is None
    assert "spring_linear_rate_assumes_loaded" in result.limitations
    assert static.halfshaft is None
    without_spring = analyze_corner(project.front, project.vehicle, [0])
    assert without_spring.samples[0] is not None and without_spring.samples[0].spring is None
    assert "spring_mount_unspecified" in without_spring.limitations


def test_analysis_reports_missing_driven_inputs() -> None:
    from suspensionlab.core.analysis import analyze_corner

    project = load_template("ring")
    project.front.drivetrain.driven = True
    result = analyze_corner(project.front, project.vehicle, [0])
    assert "halfshaft_axes_and_plunge_unspecified" in result.limitations
    assert result.samples[0] is not None and result.samples[0].halfshaft is None


def test_halfshaft_checks_are_explicit_and_include_numbers() -> None:
    from suspensionlab.core.drivetrain import HalfshaftLimits, HalfshaftMetrics, check_halfshaft

    values = HalfshaftMetrics(600, 25, 10, 14, 24, 1)
    limits = HalfshaftLimits(22, 45, 3)
    issues = check_halfshaft(values, limits, 40)
    assert [(i.code, i.value, i.limit, i.travel_mm) for i in issues] == [
        ("inner_angle", 25, 22, 40), ("plunge_max", 1, 3, 40)
    ]


def test_two_sided_projected_roll_center_is_mirrored_at_equal_travel() -> None:
    from suspensionlab.core.roll_center import roll_center_from_projected_motion

    axle = load_template("ring").front
    left, right = DoubleWishbone(axle, "left"), DoubleWishbone(axle, "right")
    lp, rp = left.solve(15), right.solve(15)
    y, z = roll_center_from_projected_motion(left, lp, right, rp)
    assert y == pytest.approx(0, abs=1e-6)
    assert z == pytest.approx(symmetric_roll_center_height(left, lp), abs=1e-6)
    asymmetric = roll_center_from_projected_motion(left, left.solve(15), right, right.solve(-10))
    assert all(math.isfinite(value) for value in asymmetric)
