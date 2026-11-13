"""Явная условная характеристика амортизатора и её энергетический баланс."""
from dataclasses import replace
from math import inf, nan

import pytest

from suspensionlab.core.damper import (
    DamperMetrics,
    LinearDamperCharacteristic,
    LowerArmDamper,
    evaluate_linear_damping,
)
from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize("ratio,velocity,expected_speed,expected_resistance,expected_wheel,expected_power", [
    (0.5, 100, 50, 100, -50, 5),
    (0.5, -100, -50, -200, 100, 10),
    (-0.5, 100, -50, -200, -100, 10),
    (-0.5, -100, 50, 100, 50, 5),
    (0.5, 0, 0, 0, 0, 0),
    (0, 100, 0, 0, 0, 0),
])
def test_damping_signs_and_power(ratio, velocity, expected_speed, expected_resistance, expected_wheel, expected_power):
    m = DamperMetrics(400, 0, ratio, None)
    result = evaluate_linear_damping(m, LinearDamperCharacteristic(2, 4), velocity)
    assert result.compression_velocity_mm_s == pytest.approx(expected_speed)
    assert result.resistance_n == pytest.approx(expected_resistance)
    assert result.wheel_force_n == pytest.approx(expected_wheel)
    assert result.dissipated_power_w == pytest.approx(expected_power)
    assert result.wheel_force_n * velocity / 1000 == pytest.approx(-result.dissipated_power_w)
    assert result.stroke_limits_checked is False


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("travel", [-20, 0, 20])
def test_speed_matches_independent_finite_difference(side, travel):
    axle = load_template("ring").front
    model = DoubleWishbone(axle, side)
    damper = LowerArmDamper(model, axle)
    metrics = damper.evaluate(model.solve(travel), StrokeLimits(350, 450))
    speed = 80
    result = evaluate_linear_damping(metrics, LinearDamperCharacteristic(1.5, 3), speed)
    delta = 0.001
    low = damper.evaluate(model.solve(travel - delta)).length_mm
    high = damper.evaluate(model.solve(travel + delta)).length_mm
    assert result.compression_velocity_mm_s == pytest.approx(-(high - low) / (2 * delta) * speed, rel=1e-6)
    assert result.dissipated_power_w >= 0
    assert result.stroke_limits_checked is True


def test_missing_and_conflicted_inputs_are_not_silently_calculated():
    c = LinearDamperCharacteristic(1, 2)
    metrics = DamperMetrics(400, 0, 0.5, None)
    for value in (nan, inf, -inf):
        with pytest.raises(ValueError):
            evaluate_linear_damping(metrics, c, value)
        with pytest.raises(ValueError):
            LinearDamperCharacteristic(value, 2)
    with pytest.raises(ValueError):
        LinearDamperCharacteristic(1, -1)
    for m in (replace(metrics, motion_ratio=None), replace(metrics, motion_ratio=nan),
              replace(metrics, length_mm=nan), replace(metrics, length_mm=0),
              replace(metrics, compression_from_static_mm=inf), replace(metrics, error="bad")):
        with pytest.raises(ValueError):
            evaluate_linear_damping(m, c, 1)
    model = DoubleWishbone(load_template("ring").front)
    damper = LowerArmDamper(model, load_template("ring").front)
    for lower, upper in ((damper.initial_length_mm, 500), (300, damper.initial_length_mm), (300, 350)):
        with pytest.raises(ValueError, match="упоре"):
            evaluate_linear_damping(damper.evaluate(model.initial_pose(), StrokeLimits(lower, upper)), c, 10)
