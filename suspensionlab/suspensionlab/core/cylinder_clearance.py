"""Расстояние оси капсулы до ограниченного сплошного цилиндра на одной позе."""
from __future__ import annotations

from dataclasses import dataclass
from math import dist, hypot, isfinite, sqrt

from .segment_clearance import Point


def _valid_point(value: Point) -> bool:
    return (isinstance(value, (tuple, list)) and len(value) == 3 and
            all(type(v) in (int, float) and isfinite(v) and abs(v) <= 1_000_000 for v in value))


def _classification(clearance: float, margin: float) -> str:
    tolerance = 1e-6
    if clearance < -tolerance:
        return 'overlap'
    if clearance <= tolerance:
        return 'touch'
    if clearance < margin - tolerance:
        return 'low_clearance'
    if margin > 0 and abs(clearance - margin) <= tolerance:
        return 'limit'
    return 'clear'


@dataclass(frozen=True, slots=True)
class CylinderClearance:
    clearance_mm: float
    status: str
    axis_point: Point
    cylinder_point: Point
    axis_parameter: float


def capsule_cylinder_clearance(a: Point, b: Point, capsule_radius: float, center: Point, axis: Point,
                               cylinder_radius: float, cylinder_width: float, margin: float) -> CylinderClearance:
    """Зазор капсулы и сплошного конечного цилиндра, через минимум на оси.

    Отрицательное значение — пересечение, но не глубина проникновения. Ось
    цилиндра — вектор направления, все размеры явно заданы. Одномерный выпуклый
    минимум дистанции до цилиндра вычисляется численно; возможна ошибка float.
    """
    if not all(_valid_point(p) for p in (a, b, center, axis)):
        raise ValueError('Некорректные координаты цилиндра или отрезка')
    for value in (capsule_radius, cylinder_radius, cylinder_width):
        if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 1_000_000:
            raise ValueError('Радиусы и ширина должны быть конечными и положительными')
    if type(margin) not in (int, float) or not isfinite(margin) or not 0 <= margin <= 1_000_000:
        raise ValueError('Запас должен быть конечным и неотрицательным')
    length = sqrt(sum(v * v for v in axis))
    if length < 1e-9:
        raise ValueError('Направление цилиндра не определено')
    unit = tuple(v / length for v in axis)
    delta = tuple(b[i] - a[i] for i in range(3))
    half = cylinder_width / 2

    def evaluate(t: float) -> tuple[float, Point, Point]:
        p: Point = tuple(a[i] + t * delta[i] for i in range(3))  # type: ignore[assignment]
        v = tuple(p[i] - center[i] for i in range(3))
        axial = sum(v[i] * unit[i] for i in range(3))
        radial = tuple(v[i] - axial * unit[i] for i in range(3))
        radial_length = hypot(*radial)
        clipped_axis = max(-half, min(half, axial))
        scale = min(1., cylinder_radius / radial_length) if radial_length else 0.
        nearest: Point = tuple(center[i] + clipped_axis * unit[i] + scale * radial[i] for i in range(3))  # type: ignore[assignment]
        return dist(p, nearest), p, nearest

    left, right = 0., 1.
    for _ in range(110):
        x, y = (2 * left + right) / 3, (left + 2 * right) / 3
        fx, fy = evaluate(x)[0], evaluate(y)[0]
        if fx < fy:
            right = y
        elif fx > fy:
            left = x
        else:
            left, right = x, y
    parameter = min((0., 1., (left + right) / 2), key=lambda t: evaluate(t)[0])
    distance, point, nearest = evaluate(parameter)
    clearance = distance - capsule_radius
    return CylinderClearance(clearance, _classification(clearance, margin), point, nearest, parameter)
