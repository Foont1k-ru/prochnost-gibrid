"""Баланс виртуальной работы для явно заданной нагрузки и пружины."""
import math

import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.equilibrium import EquilibriumError, SpringEquilibrium
from suspensionlab.core.springs import spring_wheel_support
from suspensionlab.model.templates import load_template


def test_wheel_support_preserves_motion_ratio_sign() -> None:
    assert spring_wheel_support(1000, 0.5) == 500
    assert spring_wheel_support(1000, -0.5) == -500
    assert spring_wheel_support(0, -0.5) == 0
    for force, ratio in ((-1, 1), (math.inf, 1), (1, math.nan), (1e308, 1e308)):
        with pytest.raises(ValueError):
            spring_wheel_support(force, ratio)


def test_spring_force_agrees_with_energy_derivative() -> None:
    axle = load_template("ring").front
    system = SpringEquilibrium(axle, 230, coil_bind_length_mm=150)
    point = system.evaluate(12, 1000)
    low, high = system.evaluate(11.99, 1000), system.evaluate(12.01, 1000)
    # Для линейной пружины энергия K*x²/2; её производная — сила на колесе.
    low_energy = axle.spring.rate_N_mm * low.spring.compression_mm**2 / 2
    high_energy = axle.spring.rate_N_mm * high.spring.compression_mm**2 / 2
    assert point.wheel_support_n == pytest.approx((high_energy - low_energy) / 0.02, rel=1e-7)


def test_finds_supplied_load_on_both_mirrored_sides() -> None:
    project = load_template("ring")
    left = SpringEquilibrium(project.front, 230, coil_bind_length_mm=150)
    right = SpringEquilibrium(project.front, 230, side="right", coil_bind_length_mm=150)
    load = left.evaluate(12, 1).wheel_support_n
    assert load > 0
    for system in (left, right):
        result = system.find(load, -10, 30, travel_tolerance_mm=0.0001)
        assert result.estimate.travel_mm == pytest.approx(12, abs=0.0001)
        assert result.upper.travel_mm - result.lower.travel_mm <= 0.0001
        assert result.lower.residual_n * result.upper.residual_n <= 0
        assert abs(result.estimate.residual_n) < 0.01
        assert "equilibrium_stability_not_checked" in result.limitations
        assert "spring_coil_bind_unspecified" not in result.limitations
    sample = analyze_corner(project.front, project.vehicle, [12], spring_mount="lower_arm",
                            static_spring_length_mm=230, coil_bind_length_mm=150).samples[0]
    assert sample is not None and sample.spring is not None
    assert sample.spring.wheel_support_n == pytest.approx(load)


def test_boundaries_slack_and_missing_bracket() -> None:
    axle = load_template("ring").front
    system = SpringEquilibrium(axle, 260)
    point = system.evaluate(0, 100)
    assert point.spring.status == "slack" and point.wheel_support_n == 0 and point.residual_n == -100
    with pytest.raises(ValueError, match="разные стороны"):
        system.find(10000, -5, 5)
    system = SpringEquilibrium(axle, 230)
    load = system.evaluate(-5, 1).wheel_support_n
    result = system.find(load, -5, 5)
    assert result.lower.travel_mm == result.upper.travel_mm == -5
    assert "spring_coil_bind_unspecified" in result.limitations
    for args in ((0, -5, 5), (math.nan, -5, 5), (100, 5, -5), (100, -5, math.inf)):
        with pytest.raises(ValueError):
            system.find(*args)
    with pytest.raises(ValueError):
        system.find(100, -5, 5, travel_tolerance_mm=0)


def test_undefined_force_and_invalid_geometry_stop_the_search() -> None:
    axle = load_template("ring").front
    system = SpringEquilibrium(axle, 230, coil_bind_length_mm=231)
    with pytest.raises(EquilibriumError, match="coil_bind"):
        system.find(100, 0, 1)
    axle.spring.progressive = [(0, 0), (10, 100), (20, 300)]
    system = SpringEquilibrium(axle, 220)
    with pytest.raises(EquilibriumError, match="outside_curve"):
        system.evaluate(0, 100)
    axle.spring.progressive = []
    system = SpringEquilibrium(axle, 0.01)
    with pytest.raises(EquilibriumError, match="длина пружины"):
        system.evaluate(30, 100)
    with pytest.raises(ValueError):
        SpringEquilibrium(axle, math.nan)
    with pytest.raises(ValueError):
        SpringEquilibrium(axle, 230, max_step_mm=0)


def test_progressive_knot_force_is_usable_without_a_tangent() -> None:
    axle = load_template("ring").front
    axle.spring.progressive = [(0, 0), (10, 100), (20, 300)]
    system = SpringEquilibrium(axle, 240)
    sample = system.evaluate(0, 20)
    assert sample.spring.status == "curve_knot" and sample.spring.tangent_rate_n_mm is None
    assert sample.wheel_support_n == pytest.approx(100 * sample.motion_ratio)


def test_intermediate_unavailable_force_aborts_search(monkeypatch: pytest.MonkeyPatch) -> None:
    axle = load_template("ring").front
    system = SpringEquilibrium(axle, 230)
    load = system.evaluate(12, 1).wheel_support_n
    actual = system.evaluate

    def fail_midpoint(travel_mm: float, load_n: float):
        if travel_mm == 10:
            raise EquilibriumError(travel_mm, "контрольная недоступная точка")
        return actual(travel_mm, load_n)

    monkeypatch.setattr(system, "evaluate", fail_midpoint)
    with pytest.raises(EquilibriumError, match="недоступная точка"):
        system.find(load, 0, 20)


def test_tangent_refuses_contact_knots_and_invalid_step() -> None:
    from suspensionlab.core.equilibrium import estimate_spring_support_tangent

    axle = load_template("ring").front
    slack = SpringEquilibrium(axle, 260)
    with pytest.raises(EquilibriumError, match="вне нагруженного участка"):
        estimate_spring_support_tangent(slack, 0)
    with pytest.raises(ValueError):
        estimate_spring_support_tangent(slack, 0, step_mm=0)
    with pytest.raises(ValueError):
        estimate_spring_support_tangent(slack, 1e20, step_mm=0.01)
    axle.spring.progressive = [(0, 0), (10, 100), (20, 300), (30, 500)]
    at_knot = SpringEquilibrium(axle, 240)
    with pytest.raises(EquilibriumError):
        estimate_spring_support_tangent(at_knot, 0)
    across_knot = SpringEquilibrium(axle, 240.01)
    with pytest.raises(EquilibriumError, match="излом"):
        estimate_spring_support_tangent(across_knot, 0, step_mm=1)
