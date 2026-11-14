"""Не выдаём произвольные углы при исчезновении проекции колеса."""
from __future__ import annotations

from dataclasses import replace
from math import isfinite

import pytest
from scipy.spatial.transform import Rotation

from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError
from suspensionlab.core.metrics import corner_derivatives, corner_metrics
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("axis", ["z", "y"])
@pytest.mark.parametrize("direction", [-1, 1])
def test_undefined_angles_and_derivatives_are_rejected(side: str, axis: str, direction: int) -> None:
    model = DoubleWishbone(load_template("ring").front, side)
    # Искусственная ориентация тестирует формулы проекций отдельно от решателя;
    # не утверждается, что она достижима для шаблона.
    pose = replace(model.initial_pose(), travel_mm=12.0,
                   rotation=Rotation.from_euler(axis, direction * 90, degrees=True).as_matrix())
    for calculate in (corner_metrics, corner_derivatives):
        with pytest.raises(KinematicsError, match="проекция оси колеса вырождена") as exc:
            calculate(model, pose)
        assert exc.value.travel_mm == 12


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("axis", ["z", "y"])
@pytest.mark.parametrize("direction", [-1, 1])
def test_small_but_nonzero_projections_respect_numerical_cutoff(side: str, axis: str, direction: int) -> None:
    model = DoubleWishbone(load_template("ring").front, side)
    initial = model.initial_pose()
    near = replace(initial, rotation=Rotation.from_euler(axis, direction * 89.9999999, degrees=True).as_matrix())
    with pytest.raises(KinematicsError, match="проекция оси колеса вырождена"):
        corner_metrics(model, near)
    away = replace(initial, rotation=Rotation.from_euler(axis, direction * 89.99, degrees=True).as_matrix())
    metrics = corner_metrics(model, away)
    assert isfinite(metrics.camber_deg) and isfinite(metrics.toe_deg)


@pytest.mark.parametrize("side", ["left", "right"])
def test_normal_wheel_projections_remain_usable(side: str) -> None:
    model = DoubleWishbone(load_template("ring").front, side)
    pose = model.solve(20)
    values = corner_metrics(model, pose, static_camber_deg=-2, static_toe_deg=0.5)
    rates = corner_derivatives(model, pose, static_camber_deg=-2, static_toe_deg=0.5)
    assert isfinite(values.camber_deg) and isfinite(values.toe_deg)
    assert isfinite(rates.camber_deg_per_25mm) and isfinite(rates.toe_deg_per_25mm)
