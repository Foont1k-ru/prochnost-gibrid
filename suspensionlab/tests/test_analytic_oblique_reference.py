"""Аналитический 3D-эталон наклонного параллелограмма, не измерения автомобиля.

В исходном механизме оси рычагов параллельны X, шаровые и рулевая тяга
смещены на 400 мм вдоль Y; кулак движется поступательно. Весь механизм
повёрнут вокруг Y на pitch, затем вокруг Z на yaw. Опорные формулы ниже не
используют реализацию решателя, его якобиан или вычисленные им позы.
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

import numpy as np
import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.equilibrium import SpringEquilibrium
from suspensionlab.model.entities import Axle
from suspensionlab.model.templates import load_template

# Координаты учебного плоского механизма до его наклона и поворота, мм.
POINTS = {
    "uca_f_in": (100, 300, 400), "uca_r_in": (-100, 300, 400), "ubj": (0, 700, 400),
    "lca_f_in": (100, 300, 150), "lca_r_in": (-100, 300, 150), "lbj": (0, 700, 150),
    "tierod_in": (-150, 300, 200), "tierod_out": (-150, 700, 200), "wheel_center": (0, 750, 310),
    "spring_lo": (0, 500, 150), "spring_up": (0, 450, 450),
}


def orient(point: tuple[float, float, float], yaw: float, pitch: float, sign: int = 1) -> np.ndarray:
    """Явное поворотное преобразование и отражение правой стороны."""
    x, y, z = point
    cy, sy = cos(radians(yaw)), sin(radians(yaw))
    cp, sp = cos(radians(pitch)), sin(radians(pitch))
    return np.array([cy * (cp * x + sp * z) - sy * y,
                     sign * (sy * (cp * x + sp * z) + cy * y), -sp * x + cp * z])


def build_axle(yaw: float, pitch: float) -> Axle:
    axle = load_template("ring").front
    for code, xyz in POINTS.items():
        point = axle.hardpoints[code]
        point.x, point.y, point.z = (float(v) for v in orient(xyz, yaw, pitch))
    axle.spring.free_len_mm = 250
    axle.spring.rate_N_mm = 100
    axle.spring.progressive = []
    return axle


def reference(h: float, yaw: float, pitch: float, sign: int) -> tuple[np.ndarray, float, float, float, float]:
    """Точная ветвь от статики: положение центра, длина, MR и силы.

    z перемещения центра = 400*cos(pitch)*sin(theta), пока cos(theta)>0.
    Нижнее крепление пружины находится на половине длины нижнего рычага.
    """
    cp = cos(radians(pitch))
    theta = asin(h / (400 * cp))
    c, s = cos(theta), sin(theta)
    translation = orient((0, 400 * (c - 1), 400 * s), yaw, pitch, sign)
    center = orient(POINTS["wheel_center"], yaw, pitch, sign) + translation
    dy, dz = 150 - 200 * c, 300 - 200 * s
    distance = sqrt(dy * dy + dz * dz)
    length = 230 + distance - sqrt(50**2 + 300**2)
    # MR = -dL/dh: dL/dtheta=(200*dy*sin(theta)-200*dz*cos(theta))/D.
    ratio = (200 * dz * c - 200 * dy * s) / (distance * 400 * cp * c)
    force = 100 * max(250 - length, 0)
    return center, length, ratio, force, force * ratio


@pytest.mark.parametrize("yaw,pitch", [(25.0, 15.0), (-18.0, -12.0)])
@pytest.mark.parametrize("side,sign", [("left", 1), ("right", -1)])
@pytest.mark.parametrize("travel", [-60.0, -20.0, 0.0, 20.0, 60.0])
def test_oblique_parallelogram_3d_geometry_and_spring(yaw: float, pitch: float, side: str, sign: int, travel: float) -> None:
    axle = build_axle(yaw, pitch)
    center, length, ratio, force, support = reference(travel, yaw, pitch, sign)
    model = DoubleWishbone(axle, side)
    pose = model.solve(travel, max_step_mm=1)
    np.testing.assert_allclose(pose.center, center, atol=3e-7, rtol=0)
    np.testing.assert_allclose(pose.rotation, np.eye(3), atol=1e-8, rtol=0)
    displacement = center - orient(POINTS["wheel_center"], yaw, pitch, sign)
    for name in ("ubj", "lbj", "tierod_out"):
        expected = orient(POINTS[name], yaw, pitch, sign) + displacement
        np.testing.assert_allclose(pose.point(model.points[name], model.center0), expected, atol=3e-7, rtol=0)
    sample = SpringEquilibrium(axle, 230, side=side, coil_bind_length_mm=150).evaluate(travel, 1)
    assert sample.spring.length_mm == pytest.approx(length, abs=3e-7, rel=0)
    assert sample.motion_ratio == pytest.approx(ratio, abs=1e-8, rel=0)
    assert sample.spring.force_n == pytest.approx(force, abs=3e-5, rel=0)
    assert sample.wheel_support_n == pytest.approx(support, abs=3e-5, rel=0)


@pytest.mark.parametrize("side,sign", [("left", 1), ("right", -1)])
def test_oblique_case_finds_known_balance(side: str, sign: int) -> None:
    axle = build_axle(25, 15)
    expected_travel = 17.0
    _, _, _, _, load = reference(expected_travel, 25, 15, sign)
    assert load > 0
    result = SpringEquilibrium(axle, 230, side=side, coil_bind_length_mm=150).find(
        load, 0, 30, travel_tolerance_mm=0.0001, path_step_mm=1,
    )
    assert result.lower.travel_mm <= expected_travel <= result.upper.travel_mm
    assert result.estimate.travel_mm == pytest.approx(expected_travel, abs=0.0001, rel=0)
    assert result.path is not None and result.path.completed


def test_oblique_geometry_moves_in_all_three_coordinates() -> None:
    p0, *_ = reference(0, 25, 15, 1)
    p1, *_ = reference(40, 25, 15, 1)
    assert all(abs(value) > 0.1 for value in (p1 - p0))


@pytest.mark.parametrize("yaw,pitch", [(25.0, 15.0), (-18.0, -12.0)])
@pytest.mark.parametrize("travel", [-40.0, 0.0, 40.0])
def test_reference_motion_ratio_matches_independent_length_difference(yaw: float, pitch: float, travel: float) -> None:
    """Проверяет производную самого эталона без обращения к ядру."""
    step = 0.001
    _, low, _, _, _ = reference(travel - step, yaw, pitch, 1)
    _, high, _, _, _ = reference(travel + step, yaw, pitch, 1)
    _, _, ratio, _, _ = reference(travel, yaw, pitch, 1)
    assert ratio == pytest.approx((low - high) / (2 * step), abs=1e-9, rel=0)
