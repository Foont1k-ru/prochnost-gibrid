"""Сравнение схематических осей опор пружины и амортизатора в одной позе."""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, hypot, isfinite
from typing import Literal

from .pose_view import Point, PoseView


@dataclass(frozen=True)
class AxisAlignment:
    """Острый угол осей и расстояния концов пружины до бесконечной оси амортизатора."""

    angle_deg: float
    lower_offset_mm: float
    upper_offset_mm: float


@dataclass(frozen=True)
class AxisAlignmentRow:
    travel_mm: float
    result: AxisAlignment | None
    status: Literal["available", "missing_pose", "missing_mounts", "invalid_geometry"]


def compare_mount_axes(spring: tuple[Point, Point], damper: tuple[Point, Point]) -> AxisAlignment:
    """Чистая геометрия линий; не проверяет реальные детали или их совместимость."""
    points = (*spring, *damper)
    if any(len(point) != 3 or not all(isfinite(v) for v in point) for point in points):
        raise ValueError("Координаты опор должны быть конечными трёхмерными точками")
    def sub(a: Point, b: Point) -> Point:
        return a[0] - b[0], a[1] - b[1], a[2] - b[2]
    def cross(a: Point, b: Point) -> Point:
        return a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]
    def unit(v: Point) -> Point:
        length = hypot(*v)
        if not isfinite(length) or length <= 1e-9:
            raise ValueError("Ось не определена из совпадающих или непредставимых точек")
        return v[0] / length, v[1] / length, v[2] / length
    spring_dir = unit(sub(spring[1], spring[0]))
    damper_dir = unit(sub(damper[1], damper[0]))
    dot = sum(a * b for a, b in zip(spring_dir, damper_dir, strict=True))
    angle = degrees(atan2(hypot(*cross(spring_dir, damper_dir)), abs(dot)))
    lower = hypot(*cross(sub(spring[0], damper[0]), damper_dir))
    upper = hypot(*cross(sub(spring[1], damper[0]), damper_dir))
    if not all(isfinite(x) for x in (angle, lower, upper)):
        raise ValueError("Сравнение осей не является конечным")
    return AxisAlignment(angle, lower, upper)


def compare_pose_axes(travel_mm: float, frame: PoseView | None) -> AxisAlignmentRow:
    if not isfinite(travel_mm):
        raise ValueError("Ход должен быть конечным")
    if frame is None:
        return AxisAlignmentRow(travel_mm, None, "missing_pose")
    if frame.travel_mm != travel_mm:
        raise ValueError("Положение не соответствует строке хода")
    if frame.spring is None or frame.damper is None:
        return AxisAlignmentRow(travel_mm, None, "missing_mounts")
    try:
        result = compare_mount_axes(frame.spring, frame.damper)
    except (ValueError, ArithmeticError):
        return AxisAlignmentRow(travel_mm, None, "invalid_geometry")
    return AxisAlignmentRow(travel_mm, result, "available")
