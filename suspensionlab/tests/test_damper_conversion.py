"""Условная прямая F=c*v не является восстановлением кривой амортизатора."""
from __future__ import annotations

from math import inf, nan

import pytest

from suspensionlab.core.damper import (
    DamperForcePoint,
    DamperMetrics,
    LinearDamperCharacteristic,
    evaluate_linear_damping,
    linear_coefficient_from_point,
)


def test_one_point_passes_through_origin_and_supplied_measurements():
    point = DamperForcePoint(235, 300)
    assert point.force_n == 235 and point.speed_mm_s == 300 and point.coefficient_n_s_mm == 235 / 300
    compression = linear_coefficient_from_point(235, 300)
    rebound = linear_coefficient_from_point(1342, 300)
    assert compression == pytest.approx(0.7833333333333333)
    assert rebound == pytest.approx(4.473333333333334)
    assert linear_coefficient_from_point(0, 300) == 0
    characteristic = LinearDamperCharacteristic(compression, rebound)
    metrics = DamperMetrics(400, 0, 1, None)
    assert evaluate_linear_damping(metrics, characteristic, 300).resistance_n == pytest.approx(235)
    assert evaluate_linear_damping(metrics, characteristic, -300).resistance_n == pytest.approx(-1342)


@pytest.mark.parametrize("force,speed", [
    (-1, 300), (1, 0), (1, -1), (nan, 10), (inf, 1), (10, inf), (1, nan),
    (1e308, 1e-308), (1e-308, 1e308),
])
def test_reject_invalid_division_and_nonfinite_values(force, speed):
    with pytest.raises(ValueError):
        linear_coefficient_from_point(force, speed)
    with pytest.raises(ValueError):
        DamperForcePoint(force, speed)
