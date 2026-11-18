"""Отбойник участвует в нагрузке только по явным параметрам сценария."""
import math

import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.equilibrium import EquilibriumError, SpringEquilibrium, estimate_spring_support_tangent
from suspensionlab.core.spring_characteristics import BumpStopCharacteristic, bump_stop_state
from suspensionlab.model.templates import load_template


def test_corner_reports_bump_and_combined_force_with_explicit_inputs() -> None:
    project = load_template("ring")
    stop = BumpStopCharacteristic(10, 400, 0.5, 10)
    result = analyze_corner(project.front, project.vehicle, [0, 10, 20, 30], spring_mount="lower_arm",
                            static_spring_length_mm=230, bump_stop=stop)
    clear, boundary, engaged, bottomed = result.samples
    assert all(p is not None for p in result.samples)
    assert clear is not None and clear.spring is not None and clear.bump_stop is not None
    assert clear.bump_stop.status == "clear" and clear.total_support_n == pytest.approx(clear.spring.wheel_support_n)
    assert clear.spring.frequency_hz is not None
    assert boundary is not None and boundary.bump_stop is not None and boundary.spring is not None
    assert boundary.bump_stop.status == "contact_boundary" and boundary.bump_stop.wheel_rate_n_mm is None
    assert boundary.spring.frequency_hz is None
    assert boundary.total_support_n == pytest.approx(boundary.spring.wheel_support_n)
    assert engaged is not None and engaged.bump_stop is not None and engaged.spring is not None
    assert engaged.bump_stop.status == "engaged" and engaged.bump_stop.wheel_force_n == pytest.approx(1000)
    assert engaged.spring.frequency_hz is None
    assert engaged.total_support_n == pytest.approx(engaged.spring.wheel_support_n + 1000)
    assert bottomed is not None and bottomed.bump_stop is not None and bottomed.spring is not None
    assert bottomed.bump_stop.status == "bottomed" and bottomed.total_support_n is None
    assert bottomed.spring.frequency_hz is None
    assert "spring_frequency_excludes_bump_stop" in result.limitations
    assert "bump_stop_constant_motion_ratio" in result.limitations


def test_missing_inputs_are_not_filled_in() -> None:
    project = load_template("ring")
    stop = BumpStopCharacteristic(10, 400, 0.5)
    for opts in ({}, {"spring_mount": "lower_arm"}):
        result = analyze_corner(project.front, project.vehicle, [20], bump_stop=stop, **opts)
        sample = result.samples[0]
        assert sample is not None and sample.bump_stop is not None
        assert sample.bump_stop.wheel_force_n == pytest.approx(1000)
        assert sample.total_support_n is None
        assert "bump_stop_max_compression_unspecified" in result.limitations
    no_stop = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm", static_spring_length_mm=230)
    sample = no_stop.samples[0]
    assert sample is not None and sample.bump_stop is None and sample.total_support_n is None
    assert "bump_stop_not_modeled" in no_stop.limitations
    bound = analyze_corner(project.front, project.vehicle, [20], spring_mount="lower_arm", static_spring_length_mm=230,
                           coil_bind_length_mm=245, bump_stop=stop)
    sample = bound.samples[0]
    assert sample is not None and sample.spring is not None and sample.spring.state is not None
    assert sample.spring.state.status == "coil_bind" and sample.total_support_n is None


def test_equilibrium_with_slack_spring_and_bump_stop_only() -> None:
    axle = load_template("ring").front
    stop = BumpStopCharacteristic(5, 400, 0.5, 20)
    system = SpringEquilibrium(axle, 300, bump_stop=stop)
    result = system.find(1000, 0, 30, travel_tolerance_mm=0.0001)
    assert result.estimate.travel_mm == pytest.approx(15, abs=0.0001)
    assert result.estimate.spring.status == "slack"
    assert result.estimate.wheel_support_n == 0
    assert result.estimate.total_support_n == pytest.approx(1000, abs=0.01)
    assert "bump_stop_constant_motion_ratio" in result.limitations
    assert "bump_stop_not_modeled" not in result.limitations
    with pytest.raises(EquilibriumError, match="bottomed"):
        system.evaluate(45, 1000)
    with pytest.raises(EquilibriumError, match="bottomed"):
        system.find(1000, 0, 45)


def test_spring_tangent_stays_spring_only_with_bump_stop() -> None:
    axle = load_template("ring").front
    plain = SpringEquilibrium(axle, 230)
    with_bump = SpringEquilibrium(axle, 230, bump_stop=BumpStopCharacteristic(5, 400, 0.5, 20))
    before = estimate_spring_support_tangent(plain, 10)
    after = estimate_spring_support_tangent(with_bump, 10)
    assert after.total_n_mm == pytest.approx(before.total_n_mm)
    assert after.direct_difference_n_mm == pytest.approx(before.direct_difference_n_mm)
    sample = with_bump.evaluate(10, 100)
    assert sample.bump_stop is not None and sample.total_support_n is not None
    assert sample.total_support_n == pytest.approx(sample.wheel_support_n + 500)
    assert sample.residual_n == pytest.approx(sample.total_support_n - 100)


def test_overflow_is_reported_not_returned_as_force() -> None:
    with pytest.raises(ValueError, match="конечными"):
        bump_stop_state(BumpStopCharacteristic(0, 1e308, 1), 100)
    with pytest.raises(ValueError, match="конечными"):
        bump_stop_state(BumpStopCharacteristic(-1e308, 1, 1), 1e308)
    with pytest.raises(ValueError):
        bump_stop_state(BumpStopCharacteristic(0, 1, 1), math.inf)
