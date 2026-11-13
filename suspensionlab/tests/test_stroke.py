"""Механические упоры и поиск их положения на ходе колеса."""
import numpy as np
import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.springs import lower_arm_spring_length
from suspensionlab.core.stroke import StrokeLimits, locate_lower_arm_length, stroke_state
from suspensionlab.model.templates import load_template


def test_stroke_limits_and_conflicts() -> None:
    limits = StrokeLimits(280, 420)
    assert stroke_state(300, limits).compression_clearance_mm == 20
    assert stroke_state(300, limits).extension_clearance_mm == 120
    assert stroke_state(280, limits).status == "compressed_limit"
    assert stroke_state(420, limits).status == "extended_limit"
    assert stroke_state(270, limits).status == "below_compressed"
    assert stroke_state(430, limits).status == "above_extended"
    with pytest.raises(ValueError):
        StrokeLimits(420, 280)
    with pytest.raises(ValueError):
        stroke_state(0, limits)


def test_find_length_limit_on_actual_curve() -> None:
    axle = load_template("ring").front
    model = DoubleWishbone(axle)
    lower = axle.hardpoints["damper_lo"].as_tuple()
    upper = axle.hardpoints["damper_up"].as_tuple()
    p = model.solve(12)
    target = lower_arm_spring_length(model, p, np.array(lower), np.array(upper))
    result = locate_lower_arm_length(model, lower, upper, target, 0, 30, travel_tolerance_mm=0.001)
    assert result.estimated_travel_mm == pytest.approx(12, abs=0.001)
    assert result.to_travel_mm - result.from_travel_mm <= 0.001
    assert (result.from_length_mm - target) * (result.to_length_mm - target) <= 0
    with pytest.raises(ValueError, match="разные стороны"):
        locate_lower_arm_length(model, lower, upper, target - 100, 0, 30)
