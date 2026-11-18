"""Геометрия полуоси при заданных осях валов и пределах плунжера.

Параметры ориентации и допустимого перемещения передаются явно: модель M0
не содержит всех этих данных, поэтому типовые пределы не подставляются.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import acos, degrees, isfinite

import numpy as np

from .double_wishbone import DoubleWishbone, KinematicsError, Pose

Vector3 = tuple[float, float, float]


def _vector(values: Vector3, name: str, *, direction: bool = False) -> np.ndarray:
    """Проверяет координаты или единичное направление."""
    array = np.asarray(values, dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name}: требуются три конечные координаты")
    if direction:
        norm = float(np.linalg.norm(array))
        if norm < 1e-12:
            raise ValueError(f"{name}: нулевое направление недопустимо")
        array = array / norm
    return array


@dataclass(frozen=True)
class HalfshaftGeometry:
    """Геометрия в статике для одной стороны в ISO; направления наружу.

    Внутренний ШРУС и его ось фиксированы на кузове. Наружный ШРУС и ось
    ступицы прикреплены к кулаку. Границы плунжера заданы относительно
    номинальной длины как минимальное и максимальное изменение расстояния.
    """

    inner_joint: Vector3
    outer_joint: Vector3
    inner_axis: Vector3
    outer_axis: Vector3
    nominal_length_mm: float
    plunge_min_mm: float
    plunge_max_mm: float

    def __post_init__(self) -> None:
        _vector(self.inner_joint, "Внутренний шарнир")
        _vector(self.outer_joint, "Наружный шарнир")
        _vector(self.inner_axis, "Ось внутреннего вала", direction=True)
        _vector(self.outer_axis, "Ось ступицы", direction=True)
        if not all(isfinite(v) for v in (self.nominal_length_mm, self.plunge_min_mm, self.plunge_max_mm)):
            raise ValueError("Длина и границы плунжера должны быть конечными")
        if self.nominal_length_mm <= 0 or self.plunge_min_mm >= self.plunge_max_mm:
            raise ValueError("Длина должна быть положительной, границы плунжера упорядочены")


@dataclass(frozen=True)
class HalfshaftMetrics:
    """Текущее расстояние, углы сочленений и запас плунжера."""

    length_mm: float
    inner_angle_deg: float
    outer_angle_deg: float
    plunge_mm: float
    clearance_to_min_mm: float
    clearance_to_max_mm: float


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    """Угол двух направлений в градусах, 0…180."""
    return degrees(acos(float(np.clip(np.dot(a, b), -1.0, 1.0))))


def halfshaft_metrics(model: DoubleWishbone, pose: Pose, geometry: HalfshaftGeometry) -> HalfshaftMetrics:
    """Положение привода на заданном ходе при неподвижной рейке."""
    inner = _vector(geometry.inner_joint, "Внутренний шарнир")
    outer = pose.point(_vector(geometry.outer_joint, "Наружный шарнир"), model.center0)
    diff = outer - inner
    length = float(np.linalg.norm(diff))
    if length < 1e-9:
        raise KinematicsError(pose.travel_mm, "центры шарниров полуоси совпадают")
    shaft = diff / length
    inner_axis = _vector(geometry.inner_axis, "Ось внутреннего вала", direction=True)
    outer_axis = pose.rotation @ _vector(geometry.outer_axis, "Ось ступицы", direction=True)
    plunge = length - geometry.nominal_length_mm
    return HalfshaftMetrics(
        length_mm=length,
        inner_angle_deg=_angle(shaft, inner_axis),
        outer_angle_deg=_angle(shaft, outer_axis),
        plunge_mm=plunge,
        clearance_to_min_mm=plunge - geometry.plunge_min_mm,
        clearance_to_max_mm=geometry.plunge_max_mm - plunge,
    )


@dataclass(frozen=True)
class HalfshaftLimits:
    """Паспортные угловые пределы и требуемый запас плунжера, явно заданные пользователем."""

    inner_angle_deg: float
    outer_angle_deg: float
    minimum_plunge_clearance_mm: float

    def __post_init__(self) -> None:
        values = (self.inner_angle_deg, self.outer_angle_deg, self.minimum_plunge_clearance_mm)
        if not all(isfinite(value) for value in values):
            raise ValueError("Пределы должны быть конечными")
        if not 0 < self.inner_angle_deg <= 180 or not 0 < self.outer_angle_deg <= 180:
            raise ValueError("Угловые пределы должны быть в диапазоне от 0 до 180°")
        if self.minimum_plunge_clearance_mm < 0:
            raise ValueError("Требуемый запас плунжера не может быть отрицательным")


@dataclass(frozen=True)
class HalfshaftViolation:
    """Код проверки, ход, измерение и предел; готовый текст формирует интерфейс."""

    code: str
    travel_mm: float
    value: float
    limit: float


def check_halfshaft(metrics: HalfshaftMetrics, limits: HalfshaftLimits, travel_mm: float) -> tuple[HalfshaftViolation, ...]:
    """Проверяет углы и оба запаса плунжера в одном достигнутом положении."""
    if not isfinite(travel_mm):
        raise ValueError("Ход должен быть конечным")
    problems: list[HalfshaftViolation] = []
    for code, value, limit in (
        ("inner_angle", metrics.inner_angle_deg, limits.inner_angle_deg),
        ("outer_angle", metrics.outer_angle_deg, limits.outer_angle_deg),
    ):
        if value > limit:
            problems.append(HalfshaftViolation(code, travel_mm, value, limit))
    for code, clearance in (
        ("plunge_min", metrics.clearance_to_min_mm),
        ("plunge_max", metrics.clearance_to_max_mm),
    ):
        if clearance < limits.minimum_plunge_clearance_mm:
            problems.append(HalfshaftViolation(code, travel_mm, clearance, limits.minimum_plunge_clearance_mm))
    return tuple(problems)
