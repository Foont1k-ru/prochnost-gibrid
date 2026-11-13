"""Независимые явные формулы для идеального плоского параллелограмма.

Эталон не использует решатель, метрики или результаты реализации ядра.
Это аналитический учебный случай, а не внешние измерения подвески.
"""
from __future__ import annotations

from math import sqrt

import numpy as np
import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.equilibrium import SpringEquilibrium, estimate_spring_support_tangent
from suspensionlab.core.metrics import corner_metrics
from suspensionlab.model.entities import Axle
from suspensionlab.model.templates import load_template


@pytest.fixture
def planar_axle() -> Axle:
    axle = load_template("ring").front
    points = {
        "uca_f_in": (100, 300, 400), "uca_r_in": (-100, 300, 400), "ubj": (0, 700, 400),
        "lca_f_in": (100, 300, 150), "lca_r_in": (-100, 300, 150), "lbj": (0, 700, 150),
        "tierod_in": (-150, 300, 200), "tierod_out": (-150, 700, 200), "wheel_center": (0, 750, 310),
        "spring_lo": (0, 500, 150), "spring_up": (0, 450, 450),
    }
    for name, (x, y, z) in points.items():
        p = axle.hardpoints[name]
        p.x, p.y, p.z = x, y, z
    axle.spring.free_len_mm = 250
    axle.spring.rate_N_mm = 100
    axle.spring.progressive = []
    return axle


def planar_reference(h: float) -> tuple[float, float, float, float, float, float]:
    """Независимый расчёт y колеса, L, MR, силы и её точной производной."""
    arm = 400.0
    mount_arm = 200.0
    q = sqrt(1 - (h / arm)**2)
    y_wheel = 750 + arm * (q - 1)
    y_mount = 300 + mount_arm * q
    z_mount = 150 + mount_arm * h / arm
    dy, dz = 450 - y_mount, 450 - z_mount
    distance = sqrt(dy**2 + dz**2)
    distance0 = sqrt(50**2 + 300**2)
    length = 230 + distance - distance0
    dy_dh = -mount_arm * h / (arm**2 * q)
    dz_dh = mount_arm / arm
    d2y_dh2 = -mount_arm / (arm**2 * q**3)
    numerator = dy * dy_dh + dz * dz_dh
    ratio = numerator / distance
    numerator_derivative = -dy_dh**2 + dy * d2y_dh2 - dz_dh**2
    ratio_derivative = numerator_derivative / distance + numerator**2 / distance**3
    force = 100 * max(250 - length, 0)
    wheel_force = force * ratio
    wheel_tangent = 100 * ratio**2 + force * ratio_derivative
    return y_wheel, length, ratio, force, wheel_force, wheel_tangent


@pytest.mark.parametrize("side,sign", [("left", 1), ("right", -1)])
@pytest.mark.parametrize("travel", [-60.0, -20.0, 0.0, 20.0, 60.0])
def test_analytic_planar_motion_and_support(planar_axle: Axle, side: str, sign: int, travel: float) -> None:
    expected_y, length, ratio, force, wheel_force, _ = planar_reference(travel)
    model = DoubleWishbone(planar_axle, side)
    pose = model.solve(travel)
    assert pose.center == pytest.approx([0, sign * expected_y, 310 + travel], abs=2e-7)
    np.testing.assert_allclose(pose.rotation, np.eye(3), atol=1e-8)
    metrics = corner_metrics(model, pose)
    assert metrics.camber_deg == pytest.approx(0, abs=1e-7)
    assert metrics.toe_deg == pytest.approx(0, abs=1e-7)
    problem = SpringEquilibrium(planar_axle, 230, side=side, coil_bind_length_mm=150)
    point = problem.evaluate(travel, 1)
    assert point.spring.length_mm == pytest.approx(length, abs=2e-7)
    assert point.motion_ratio == pytest.approx(ratio, abs=1e-8)
    assert point.spring.force_n == pytest.approx(force, abs=2e-5)
    assert point.wheel_support_n == pytest.approx(wheel_force, abs=2e-5)


@pytest.mark.parametrize("side", ["left", "right"])
def test_analytic_equilibrium_and_geometric_tangent(planar_axle: Axle, side: str) -> None:
    travel = 17.0
    _, _, ratio, force, load, derivative = planar_reference(travel)
    problem = SpringEquilibrium(planar_axle, 230, side=side, coil_bind_length_mm=150)
    result = problem.find(load, 0, 40, travel_tolerance_mm=0.0001)
    assert result.estimate.travel_mm == pytest.approx(travel, abs=0.0001)
    assert result.lower.travel_mm <= travel <= result.upper.travel_mm
    assert result.evaluations > 3
    tangent = estimate_spring_support_tangent(problem, travel, step_mm=0.01)
    assert tangent.elastic_component_n_mm == pytest.approx(100 * ratio**2, abs=1e-7)
    assert tangent.geometric_component_n_mm == pytest.approx(derivative - 100 * ratio**2, abs=1e-6)
    assert tangent.total_n_mm == pytest.approx(derivative, abs=1e-6)
    assert tangent.direct_difference_n_mm == pytest.approx(derivative, abs=1e-6)
    assert abs(tangent.geometric_component_n_mm) > 0.1
    assert force > 0


def test_geometric_term_can_make_tangent_negative(planar_axle: Axle) -> None:
    # При близко расположенной верхней опоре ориентация пружины быстро меняется.
    planar_axle.hardpoints["spring_up"].z = 160
    problem = SpringEquilibrium(planar_axle, 230, coil_bind_length_mm=150)
    coarse = estimate_spring_support_tangent(problem, 0, step_mm=0.1)
    fine = estimate_spring_support_tangent(problem, 0, step_mm=0.01)
    assert fine.elastic_component_n_mm > 0
    assert fine.geometric_component_n_mm < 0
    assert fine.total_n_mm < 0  # Не обрезаем знак квадратом MR.
    assert fine.total_n_mm == pytest.approx(fine.direct_difference_n_mm, abs=1e-6)
    assert coarse.total_n_mm == pytest.approx(fine.total_n_mm, abs=1e-4)


def test_combined_equilibrium_matches_analytic_forces(planar_axle: Axle) -> None:
    from suspensionlab.core.spring_characteristics import BumpStopCharacteristic

    # Отбойник: K = 400 Н/мм, MR = 0,5, включение на 5 мм.
    target_travel = 17.0
    spring_force = planar_reference(target_travel)[4]
    bump_force = 400 * 0.5**2 * (target_travel - 5)
    problem = SpringEquilibrium(planar_axle, 230, coil_bind_length_mm=150,
                                bump_stop=BumpStopCharacteristic(5, 400, 0.5, 20))
    result = problem.find(spring_force + bump_force, 0, 30, travel_tolerance_mm=0.0001)
    assert result.estimate.travel_mm == pytest.approx(target_travel, abs=0.0001)
    assert result.estimate.bump_stop is not None
    assert result.estimate.bump_stop.wheel_force_n == pytest.approx(bump_force, abs=0.01)
    assert result.estimate.total_support_n == pytest.approx(spring_force + bump_force, abs=0.02)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("travel", [-60.0, 0.0, 60.0])
def test_damper_displacement_against_analytic_geometry(planar_axle: Axle, side: str, travel: float) -> None:
    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.stroke import StrokeLimits

    for source, destination in (("spring_lo", "damper_lo"), ("spring_up", "damper_up")):
        a, b = planar_axle.hardpoints[source], planar_axle.hardpoints[destination]
        b.x, b.y, b.z = a.x, a.y, a.z
    expected_length = planar_reference(travel)[1] - 230 + sqrt(50**2 + 300**2)
    initial = sqrt(50**2 + 300**2)
    project = load_template("ring")
    sample = analyze_corner(planar_axle, project.vehicle, [travel], side=side, damper_mount="lower_arm",
                            damper_limits=StrokeLimits(250, 350)).samples[0]
    assert sample is not None and sample.damper is not None and sample.damper.stroke is not None
    assert sample.damper.length_mm == pytest.approx(expected_length, abs=2e-7)
    assert sample.damper.compression_from_static_mm == pytest.approx(initial - expected_length, abs=2e-7)
    assert sample.damper.motion_ratio == pytest.approx(planar_reference(travel)[2], abs=1e-8)
    assert sample.damper.stroke.compression_clearance_mm == pytest.approx(expected_length - 250, abs=2e-7)


def test_coincident_damper_mounts_do_not_abort_other_sweep_points(planar_axle: Axle) -> None:
    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.spring_characteristics import BumpStopCharacteristic
    from suspensionlab.core.stroke import StrokeLimits

    a, b = planar_axle.hardpoints["damper_lo"], planar_axle.hardpoints["damper_up"]
    a.x, a.y, a.z = 0, 500, 150
    b.x, b.y, b.z = 0, 300 + 200 * sqrt(1 - (20 / 400)**2), 160
    project = load_template("ring")
    result = analyze_corner(planar_axle, project.vehicle, [0, 20, 25], spring_mount="lower_arm",
                            static_spring_length_mm=230, bump_stop=BumpStopCharacteristic(100, 100, 1),
                            damper_mount="lower_arm", damper_limits=StrokeLimits(1, 100))
    earlier, singular, later = result.samples
    assert earlier is not None and earlier.damper is not None and earlier.damper.error is None
    assert singular is not None and singular.damper is not None and singular.damper.error is not None
    assert singular.damper.motion_ratio is None and singular.damper.stroke is None
    assert singular.spring is not None and singular.spring.frequency_hz is None
    assert singular.total_support_n is None
    assert later is not None and later.damper is not None and later.damper.error is None
