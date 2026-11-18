"""Общая геометрия одной круглой дуги в осевой линии трубы, без CAD и подвески.

Точка поворота — пересечение продолжений прямых, НЕ точка на дуге. Координаты
абсолютные. Физика гибки, технологические минимумы и припуски не моделируются.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

Point3 = tuple[float, float, float]
MAX_COORDINATE = 1_000_000.0  # защитные пределы, не производственные допуски
MIN_SEGMENT = 0.01
MIN_ANGLE_RAD = 1e-6


class BentTubeError(ValueError):
    """Осевая линия не может быть построена из заданных данных."""


def _vector(value: Any) -> Point3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise BentTubeError("expected three coordinates")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise BentTubeError("invalid coordinate")
        try:
            number = float(item)
        except (ValueError, OverflowError) as error:
            raise BentTubeError("invalid coordinate") from error
        if not math.isfinite(number) or abs(number) > MAX_COORDINATE:
            raise BentTubeError("coordinate outside bounds")
        result.append(number)
    return (result[0], result[1], result[2])


def _positive(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BentTubeError("invalid radius")
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise BentTubeError("invalid radius") from error
    if not math.isfinite(number) or not MIN_SEGMENT <= number <= MAX_COORDINATE:
        raise BentTubeError("radius outside bounds")
    return number


def _sub(a: Point3, b: Point3) -> Point3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _add_scaled(a: Point3, b: Point3, scale: float) -> Point3:
    return a[0] + b[0] * scale, a[1] + b[1] * scale, a[2] + b[2] * scale


def _unit(v: Point3, minimum: float = MIN_SEGMENT) -> Point3:
    length = math.hypot(*v)
    if length < minimum:
        raise BentTubeError("coincident bend vertex or end")
    return v[0] / length, v[1] / length, v[2] / length


@dataclass(frozen=True, slots=True)
class BendPath:
    start: Point3
    vertex: Point3
    end: Point3
    tangent_start: Point3
    tangent_end: Point3
    center: Point3
    midpoint: Point3
    radius: float
    sweep_rad: float
    length: float

    def sample(self, steps: int = 24) -> tuple[Point3, ...]:
        """Приближённая осевая линия только для 2D-эскиза, не CAD и не изготовление."""
        if not 1 <= steps <= 256:
            raise BentTubeError("invalid sampling")
        a = _sub(self.tangent_start, self.center)
        b = _sub(self.tangent_end, self.center)
        u = tuple(x / self.radius for x in a)
        sine, cosine = math.sin(self.sweep_rad), math.cos(self.sweep_rad)
        v = tuple((b[i] / self.radius - u[i] * cosine) / sine for i in range(3))
        arc: list[Point3] = []
        for i in range(steps + 1):
            angle = self.sweep_rad * i / steps
            arc.append(tuple(self.center[j] + self.radius * (u[j] * math.cos(angle) + v[j] * math.sin(angle))
                             for j in range(3)))  # type: ignore[arg-type]
        return (self.start, *arc, self.end)


def make_bend_path(start: Any, vertex: Any, end: Any, bend_radius: Any, tube_radius: Any) -> BendPath:
    """Две прямые и касательная дуга; все входы явно заданы пользователем.

    Чисто геометрическая проверка: не утверждает возможность гибки или сборки.
    """
    a, p, b = _vector(start), _vector(vertex), _vector(end)
    r, outer = _positive(bend_radius), _positive(tube_radius)
    if r - outer < MIN_SEGMENT:
        raise BentTubeError("bend radius must exceed outer tube radius")
    first, second = _sub(a, p), _sub(b, p)
    la, lb = math.hypot(*first), math.hypot(*second)
    u, v = _unit(first), _unit(second)
    dot = max(-1.0, min(1.0, sum(u[i] * v[i] for i in range(3))))
    cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    theta = math.atan2(math.hypot(*cross), dot)
    if theta < MIN_ANGLE_RAD or math.pi - theta < MIN_ANGLE_RAD:
        raise BentTubeError("bend plane or angle is degenerate")
    offset = r / math.tan(theta / 2)
    if not math.isfinite(offset) or offset + MIN_SEGMENT > min(la, lb):
        raise BentTubeError("bend does not fit between endpoints")
    bisector = _unit((u[0] + v[0], u[1] + v[1], u[2] + v[2]), 1e-9)
    tangent_a = _add_scaled(p, u, offset)
    tangent_b = _add_scaled(p, v, offset)
    center = _add_scaled(p, bisector, r / math.sin(theta / 2))
    toward_vertex = _unit(_sub(p, center))
    midpoint = _add_scaled(center, toward_vertex, r)
    sweep = math.pi - theta
    length = la + lb - 2 * offset + r * sweep
    return BendPath(a, p, b, tangent_a, tangent_b, center, midpoint, r, sweep, length)
