"""Расчёт оси крена и размерный контроль оценочных формул."""
import math

import pytest

from suspensionlab.core.vehicle_metrics import (
    RollCenter3D,
    geometric_load_transfer_n,
    roll_axis,
    static_roll_angle_deg,
)


def test_roll_axis_in_iso_and_height_at_cg() -> None:
    axis = roll_axis(RollCenter3D(0, 0, 40), RollCenter3D(-2500, 0, 90))
    assert axis.pitch_deg == pytest.approx(math.degrees(math.atan2(50, 2500)))
    assert axis.height_at_x(-1250) == pytest.approx(65)
    assert axis.lateral_angle_deg == 0


def test_roll_axis_rejects_invalid_geometry() -> None:
    with pytest.raises(ValueError):
        roll_axis(RollCenter3D(0, 0, 40), RollCenter3D(0, 0, 90))
    with pytest.raises(ValueError):
        RollCenter3D(0, float("nan"), 1)


def test_geometric_transfer_preserves_sign() -> None:
    assert geometric_load_transfer_n(700, 9.80665, 80, 1600) == pytest.approx(343.23275)
    assert geometric_load_transfer_n(700, -9.80665, 80, 1600) == pytest.approx(-343.23275)
    assert geometric_load_transfer_n(700, 9.80665, -80, 1600) < 0
    with pytest.raises(ValueError):
        geometric_load_transfer_n(700, 9.8, 80, 0)


def test_static_roll_linear_formula_and_instability() -> None:
    angle = static_roll_angle_deg(1000, 9.80665, 400, 600, 400)
    expected_rad = 1000 * 9.80665 * 0.4 / (1000 / math.radians(1) - 1000 * 9.80665 * 0.4)
    assert angle == pytest.approx(math.degrees(expected_rad))
    assert static_roll_angle_deg(1000, -9.80665, 400, 600, 400) == pytest.approx(-angle)
    with pytest.raises(ValueError, match="неустойчиво"):
        static_roll_angle_deg(1000, 9.8, 1000, 1, 1)
