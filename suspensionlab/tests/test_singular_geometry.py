"""Граничные случаи кинематики: аналитическая окружность и потеря ранга."""
from __future__ import annotations

from math import sqrt

import numpy as np
import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError
from suspensionlab.core.screw_axis import instantaneous_motion
from suspensionlab.model.entities import Axle
from suspensionlab.model.templates import load_template


def planar_geometry() -> Axle:
    """Параллелограмм с радиусом 400 мм; |ход| > 400 невозможен."""
    axle = load_template("ring").front
    points = {
        "uca_f_in": (100, 300, 400), "uca_r_in": (-100, 300, 400), "ubj": (0, 700, 400),
        "lca_f_in": (100, 300, 150), "lca_r_in": (-100, 300, 150), "lbj": (0, 700, 150),
        "tierod_in": (-150, 300, 200), "tierod_out": (-150, 700, 200), "wheel_center": (0, 750, 310),
    }
    for name, (x, y, z) in points.items():
        point = axle.hardpoints[name]
        point.x, point.y, point.z = x, y, z
    return axle


@pytest.mark.parametrize("side", ["left", "right"])
def test_static_arm_axis_rank_loss_is_rejected(side: str) -> None:
    axle = planar_geometry()
    # Шаровая на оси рычага, хотя внутренние точки и длины связей различны.
    axle.hardpoints["ubj"].y = 300
    with pytest.raises(KinematicsError, match="сингулярности") as exc:
        DoubleWishbone(axle, side)
    assert exc.value.travel_mm == 0


@pytest.mark.parametrize("side", ["left", "right"])
def test_condition_detects_approaching_static_rank_loss(side: str) -> None:
    conditions = []
    for offset in (0.01, 0.001, 0.0001):
        axle = planar_geometry()
        axle.hardpoints["ubj"].y = 300 + offset
        conditions.append(DoubleWishbone(axle, side).initial_pose().condition)
    assert all(a < b for a, b in zip(conditions, conditions[1:], strict=False))
    assert conditions[-1] > 1e6
    axle.hardpoints["ubj"].y = 300 + 0.000001
    with pytest.raises(KinematicsError, match="сингулярности"):
        DoubleWishbone(axle, side)


@pytest.mark.parametrize("side,sign", [("left", 1), ("right", -1)])
@pytest.mark.parametrize("travel", [-399.0, -390.0, 390.0, 399.0])
def test_near_travel_limit_against_circle(side: str, sign: int, travel: float) -> None:
    model = DoubleWishbone(planar_geometry(), side)
    pose = model.solve(travel, max_step_mm=1)
    radius_projection = sqrt(400**2 - travel**2)
    assert pose.center[1] == pytest.approx(sign * (350 + radius_projection), abs=1e-6)
    motion = instantaneous_motion(model, pose)
    np.testing.assert_allclose(motion.linear, [0, -sign * travel / radius_projection, 1], atol=1e-6, rtol=0)
    assert pose.residual_mm < 1e-8


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("direction", [-1, 1])
def test_failed_branch_does_not_fabricate_samples_or_stop_other_branch(side: str, direction: int) -> None:
    axle = planar_geometry()
    # Порядок намеренно не сортирован; одна ветвь пересекает предел окружности.
    travels = [direction * 405, -direction * 50, direction * 399, 0, direction * 401, direction * 405]
    result = analyze_corner(axle, load_template("ring").vehicle, travels, side=side, max_step_mm=1)
    points = result.sweep.points
    assert [point.travel_mm for point in points] == travels
    assert [sample is not None for sample in result.samples] == [False, True, True, True, False, False]
    assert all(points[i].pose is None and points[i].error is not None for i in (0, 4, 5))
    failure = points[4].error
    assert failure is not None
    assert 399 < direction * failure.travel_mm <= 401
    assert points[0].error is failure and points[5].error is failure
    assert all(points[i].error is None and points[i].pose is not None for i in (1, 2, 3))
    failed_bound = result.sweep.reachable_bump_mm if direction == 1 else -result.sweep.reachable_droop_mm
    other_bound = -result.sweep.reachable_droop_mm if direction == 1 else result.sweep.reachable_bump_mm
    assert 399 <= failed_bound <= 400
    assert other_bound == pytest.approx(50)
