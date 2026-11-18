"""Проверки трёхмерных связей, знаков, продолжения и формул жёсткости."""
from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from suspensionlab.core.coords import iso_to_sae, sae_to_iso
from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError
from suspensionlab.core.metrics import corner_metrics
from suspensionlab.core.springs import ride_frequency_hz, ride_rate, wheel_rate
from suspensionlab.model.templates import load_template


@pytest.fixture
def solver() -> DoubleWishbone:
    return DoubleWishbone(load_template("ring").front)


def test_iso_sae_round_trip() -> None:
    assert iso_to_sae((1, 2, 3)) == (1, -2, -3)
    assert sae_to_iso(iso_to_sae((1, 2, 3))) == (1, 2, 3)


def test_rest_and_constraints_on_full_travel(solver: DoubleWishbone) -> None:
    for pose in solver.sweep(list(np.linspace(-35, 40, 31))):
        for moving, fixed in solver._pairs:
            point = pose.point(solver.points[moving], solver.center0)
            assert np.linalg.norm(point - solver.points[fixed]) == pytest.approx(
                np.linalg.norm(solver.points[moving] - solver.points[fixed]), abs=1e-7
            )
        assert pose.center[2] == pytest.approx(solver.center0[2] + pose.travel_mm, abs=1e-8)
        assert np.linalg.det(pose.rotation) == pytest.approx(1.0, abs=1e-10)


def test_analytic_jacobian_matches_finite_difference(solver: DoubleWishbone) -> None:
    pose = solver.solve(12)
    residual, jac = solver._system(pose.center, pose.rotation, pose.travel_mm)
    for i in range(6):
        delta = np.zeros(6)
        delta[i] = 1e-6
        center = pose.center + delta[:3]
        rotation = Rotation.from_rotvec(delta[3:]).as_matrix() @ pose.rotation
        actual, _ = solver._system(center, rotation, pose.travel_mm)
        np.testing.assert_allclose((actual - residual) / 1e-6, jac[:, i], atol=4e-4, rtol=1e-5)


def test_left_right_symmetry() -> None:
    axle = load_template("ring").front
    left, right = DoubleWishbone(axle, "left"), DoubleWishbone(axle, "right")
    for travel in (-30, 0, 30):
        a, b = left.solve(travel), right.solve(travel)
        np.testing.assert_allclose(a.center * [1, -1, 1], b.center, atol=1e-7)
        ma, mb = corner_metrics(left, a), corner_metrics(right, b)
        for key in ma.__dataclass_fields__:
            assert getattr(ma, key) == pytest.approx(getattr(mb, key), abs=1e-7)


def test_static_signs(solver: DoubleWishbone) -> None:
    m = corner_metrics(solver, solver.initial_pose())
    assert m.camber_deg == pytest.approx(0)
    assert m.toe_deg == pytest.approx(0)
    assert m.kpi_deg > 0
    assert m.caster_deg > 0
    assert m.scrub_radius_mm > 0


def test_degenerate_geometry_reported() -> None:
    axle = load_template("ring").front
    a = axle.hardpoints["uca_f_in"]
    b = axle.hardpoints["uca_r_in"]
    b.x, b.y, b.z = a.x, a.y, a.z
    with pytest.raises(KinematicsError, match="совпадают"):
        DoubleWishbone(axle)


def test_unreachable_travel_is_reported(solver: DoubleWishbone) -> None:
    with pytest.raises(KinematicsError, match="ходе"):
        solver.solve(2000, max_step_mm=2)


def test_sweep_matches_individual_and_preserves_order(solver: DoubleWishbone) -> None:
    values = [25.0, -15.0, 0.0, 25.0, -30.0]
    for p, v in zip(solver.sweep(values), values, strict=True):
        assert p.travel_mm == pytest.approx(v)
        np.testing.assert_allclose(p.center, solver.solve(v).center, atol=1e-6)


def test_spring_and_frequency_units() -> None:
    assert wheel_rate(100, 0.6) == pytest.approx(36)
    assert ride_rate(36, 220) == pytest.approx(30.9375)
    assert ride_frequency_hz(30.9375, 300) == pytest.approx(math.sqrt(30937.5 / 300) / (2 * math.pi))
    with pytest.raises(ValueError):
        ride_frequency_hz(10, 0)


def test_equal_parallel_arms_follow_circle() -> None:
    """Параллелограмм сохраняет развал, но движется по дуге, не вертикально."""
    axle = load_template("ring").front
    coords = {
        "uca_f_in": (100, 300, 400), "uca_r_in": (-100, 300, 400), "ubj": (0, 700, 400),
        "lca_f_in": (100, 300, 150), "lca_r_in": (-100, 300, 150), "lbj": (0, 700, 150),
        "tierod_in": (-150, 300, 200), "tierod_out": (-150, 700, 200), "wheel_center": (0, 750, 310),
    }
    for code, (x, y, z) in coords.items():
        point = axle.hardpoints[code]
        point.x, point.y, point.z = x, y, z
    solver = DoubleWishbone(axle)
    for travel in (-30, 0, 30):
        pose = solver.solve(travel)
        metric = corner_metrics(solver, pose)
        assert metric.camber_deg == pytest.approx(0, abs=1e-7)
        assert metric.toe_deg == pytest.approx(0, abs=1e-7)
        expected_y = 750 + math.sqrt(400**2 - travel**2) - 400
        assert pose.center[1] == pytest.approx(expected_y, abs=1e-7)


@pytest.mark.parametrize("seed", range(20))
def test_perturbed_geometries_converge(seed: int) -> None:
    """Двадцать разных трёхмерных геометрий и обе ветви хода."""
    axle = load_template("ring").front
    rng = np.random.default_rng(seed)
    for code in ("uca_f_in", "uca_r_in", "ubj", "lca_f_in", "lca_r_in", "lbj", "tierod_in", "tierod_out"):
        point = axle.hardpoints[code]
        delta = rng.uniform(-8, 8, 3)
        point.x += delta[0]
        point.y += delta[1]
        point.z += delta[2]
    solver = DoubleWishbone(axle)
    for pose in solver.sweep([-25, -10, 0, 10, 25]):
        assert pose.residual_mm < 1e-8
        assert pose.condition < 1e8


def test_instantaneous_motion_matches_finite_difference(solver: DoubleWishbone) -> None:
    from suspensionlab.core.screw_axis import instantaneous_motion

    pose = solver.solve(10)
    motion = instantaneous_motion(solver, pose)
    low, high = solver.sweep([9.99, 10.01])
    np.testing.assert_allclose(motion.linear, (high.center - low.center) / 0.02, atol=1e-7)
    omega = Rotation.from_matrix(high.rotation @ low.rotation.T).as_rotvec() / 0.02
    np.testing.assert_allclose(motion.angular, omega, atol=1e-8)
    assert motion.axis_point is not None
    velocity_on_axis = motion.linear + np.cross(motion.angular, motion.axis_point - pose.center)
    assert np.linalg.norm(np.cross(velocity_on_axis, motion.angular)) < 1e-10


def test_motion_ratio_finite_difference(solver: DoubleWishbone) -> None:
    from suspensionlab.core.springs import lower_arm_motion_ratio, lower_arm_spring_length

    axle = load_template("ring").front
    lower = np.array(axle.hardpoints["spring_lo"].as_tuple())
    upper = np.array(axle.hardpoints["spring_up"].as_tuple())
    ratio = lower_arm_motion_ratio(solver, 0, lower, upper)
    low, high = solver.sweep([-0.1, 0.1])
    independent = (lower_arm_spring_length(solver, low, lower, upper) - lower_arm_spring_length(solver, high, lower, upper)) / 0.2
    assert ratio == pytest.approx(independent, abs=1e-6)
    assert ratio > 0


def test_ring_regression_fixture() -> None:
    """Регрессионный снимок выходов; не является независимым физическим эталоном."""
    import json
    from pathlib import Path

    fixture = json.loads((Path(__file__).parent / "data" / "ring_double_wishbone_regression.json").read_text(encoding="utf-8"))
    model = DoubleWishbone(load_template(fixture["template"]).front)
    for case in fixture["cases"]:
        metric = corner_metrics(model, model.solve(case["travel_mm"]))
        for name in ("camber_deg", "toe_deg", "scrub_radius_mm", "longitudinal_displacement_mm"):
            assert getattr(metric, name) == pytest.approx(case[name], abs=1e-6)


def test_corner_derivatives_match_finite_difference() -> None:
    from suspensionlab.core.metrics import corner_derivatives

    axle = load_template("ring").front
    for side in ("left", "right"):
        model = DoubleWishbone(axle, side)
        for travel in (-20, 0, 20):
            pose = model.solve(travel)
            derivative = corner_derivatives(model, pose, static_camber_deg=-2.5, static_toe_deg=0.1)
            lower, upper = model.sweep([travel - 0.005, travel + 0.005])
            a = corner_metrics(model, lower, static_camber_deg=-2.5, static_toe_deg=0.1)
            b = corner_metrics(model, upper, static_camber_deg=-2.5, static_toe_deg=0.1)
            assert derivative.camber_deg_per_25mm == pytest.approx((b.camber_deg - a.camber_deg) * 2500, abs=1e-6)
            assert derivative.toe_deg_per_25mm == pytest.approx((b.toe_deg - a.toe_deg) * 2500, abs=1e-6)
            assert derivative.lateral_mm_per_mm == pytest.approx((b.lateral_displacement_mm - a.lateral_displacement_mm) * 100, abs=1e-7)
            assert derivative.longitudinal_mm_per_mm == pytest.approx((b.longitudinal_displacement_mm - a.longitudinal_displacement_mm) * 100, abs=1e-7)


def test_continuation_rejects_extreme_step_counts(solver: DoubleWishbone) -> None:
    from suspensionlab.core.sweep import limited_sweep

    with pytest.raises(ValueError, match="Слишком много шагов"):
        solver.solve(100, max_step_mm=0.000001)
    with pytest.raises(ValueError, match="Слишком много шагов"):
        solver.sweep([-100, 100], max_step_mm=0.001)
    with pytest.raises(ValueError, match="Слишком много шагов"):
        limited_sweep(solver, [100], max_step_mm=0.000001)
