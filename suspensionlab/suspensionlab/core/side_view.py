"""Проекционный мгновенный центр в боковом виде и оценки антиэффектов."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np

from .double_wishbone import DoubleWishbone, KinematicsError, Pose
from .screw_axis import instantaneous_motion


@dataclass(frozen=True)
class SideInstantCenter:
    """Однородные координаты бокового центра в плоскости XZ."""

    x: float
    z: float
    w: float

    @property
    def at_infinity(self) -> bool:
        """Параллельные нормали задают направление центра на бесконечности."""
        return abs(self.w) < 1e-10


def projected_side_instant_center(model: DoubleWishbone, pose: Pose) -> SideInstantCenter:
    """Строит проекционный центр по нормалям скоростей двух шаровых.

    В общем случае пространственных скоростей это боковая проекция, а не
    силовой мгновенный центр. Точки шаровых могут иметь разные координаты Y.
    """
    motion = instantaneous_motion(model, pose)
    lines = []
    for code in ("ubj", "lbj"):
        point = pose.point(model.points[code], model.center0)
        velocity = motion.linear + np.cross(motion.angular, point - pose.center)
        vx, vz = velocity[0], velocity[2]
        speed = float(np.hypot(vx, vz))
        if speed < 1e-12:
            raise KinematicsError(pose.travel_mm, "направление скорости шаровой в боковом виде не определено")
        lines.append(np.array([vx / speed, vz / speed, -(vx * point[0] + vz * point[2]) / speed]))
    center = np.cross(lines[0], lines[1])
    norm = float(np.hypot(center[0], center[1]))
    if abs(center[2]) < 1e-10:
        if norm < 1e-10:
            raise KinematicsError(pose.travel_mm, "нормали бокового мгновенного центра совпадают")
        center = center / norm
        return SideInstantCenter(float(center[0]), float(center[1]), 0.0)
    center = center / center[2]
    return SideInstantCenter(float(center[0]), float(center[1]), 1.0)


def side_force_line_slope(
    center: SideInstantCenter, contact_x_mm: float, contact_z_mm: float, *, force_direction_x: Literal[-1, 1]
) -> float:
    """Вертикальный подъём линии на 1 мм в заданном продольном направлении.

    Это геометрический наклон, а не определение реального направления
    реакции при торможении или разгоне. Направление +1 — вперёд по X,
    -1 — назад; выбор принадлежит вызывающему расчётному сценарию.
    """
    if force_direction_x not in (-1, 1):
        raise ValueError("Продольное направление должно быть +1 или -1")
    if not all(isfinite(v) for v in (center.x, center.z, center.w, contact_x_mm, contact_z_mm)):
        raise ValueError("Координаты и направление должны быть конечными")
    dx = center.x - contact_x_mm * center.w
    dz = center.z - contact_z_mm * center.w
    if abs(dx) < 1e-12:
        raise ValueError("Боковая линия силы вертикальна или не определена")
    return float(force_direction_x * dz / dx)


def anti_effect_percent(slope: float, wheelbase_mm: float, cg_height_mm: float, axle_force_fraction: float) -> float:
    """Геометрическая оценка антиэффекта при явно заданной доле продольной силы.

    Формула `100 * slope * wheelbase / cg_height * axle_force_fraction`.
    Доли торможения/тяги, режим и знак линии не выводятся из проекта.
    Это не силовой расчёт и не расчёт динамического переноса нагрузки.
    """
    if not all(isfinite(v) for v in (slope, wheelbase_mm, cg_height_mm, axle_force_fraction)):
        raise ValueError("Параметры оценки должны быть конечными")
    if wheelbase_mm <= 0 or cg_height_mm <= 0 or not 0 <= axle_force_fraction <= 1:
        raise ValueError("База и высота ЦТ должны быть положительными, доля силы — от 0 до 1")
    return 100 * slope * wheelbase_mm / cg_height_mm * axle_force_fraction


@dataclass(frozen=True)
class LongitudinalScenario:
    """Явно выбранное направление линии и доля продольной силы на оси."""

    force_direction_x: Literal[-1, 1]
    axle_force_fraction: float

    def __post_init__(self) -> None:
        if self.force_direction_x not in (-1, 1):
            raise ValueError("Продольное направление должно быть +1 или -1")
        if not isfinite(self.axle_force_fraction) or not 0 <= self.axle_force_fraction <= 1:
            raise ValueError("Доля продольной силы должна находиться между 0 и 1")


@dataclass(frozen=True)
class SideMetrics:
    """Боковой МЦ и геометрическая оценка для заданного сценария."""

    instant_center: SideInstantCenter
    force_line_slope: float
    anti_percent: float


def evaluate_side_scenario(
    model: DoubleWishbone,
    pose: Pose,
    scenario: LongitudinalScenario,
    *,
    wheelbase_mm: float,
    cg_height_mm: float,
) -> SideMetrics:
    """Применяет сценарий к приближённому пятну под центром колеса."""
    center = projected_side_instant_center(model, pose)
    slope = side_force_line_slope(center, float(pose.center[0]), 0.0, force_direction_x=scenario.force_direction_x)
    percent = anti_effect_percent(slope, wheelbase_mm, cg_height_mm, scenario.axle_force_fraction)
    return SideMetrics(center, slope, percent)
