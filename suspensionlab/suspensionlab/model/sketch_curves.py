"""Аналитические ограниченные кривые плоского эскиза.

Численная геометрия для инструментов, не доказательство пригодности CAD.
"""
from __future__ import annotations

from math import atan2, cos, degrees, hypot, pi, radians, sin, sqrt

from .sketch_draft import Entity, Point, arc_end

NUMERIC_EPS_MM = 1e-8
INTERSECTION_EPS_MM = 1e-7
TAU = 2 * pi


class AmbiguousIntersectionError(ValueError):
    """Наложение или неустойчивое пересечение нельзя безопасно обрезать."""


def distance(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def endpoints(e: Entity) -> tuple[Point, ...]:
    if e.kind == "line":
        return e.start, e.end
    if e.kind == "arc":
        return e.end, arc_end(e)
    return ()


def point_at(e: Entity, t: float) -> Point:
    if e.kind == "line":
        return (e.start[0] + t * (e.end[0] - e.start[0]), e.start[1] + t * (e.end[1] - e.start[1]))
    if e.kind == "circle":
        angle = TAU * t
    else:
        assert e.sweep_deg is not None
        angle = atan2(e.end[1] - e.start[1], e.end[0] - e.start[0]) + radians(e.sweep_deg) * t
    return e.start[0] + e.size * cos(angle), e.start[1] + e.size * sin(angle)


def parameter(e: Entity, point: Point, eps: float = INTERSECTION_EPS_MM) -> float | None:
    """Параметр точки только если она лежит на ограниченной кривой."""
    if e.kind == "line":
        v = _sub(e.end, e.start)
        d = _sub(point, e.start)
        t = (d[0] * v[0] + d[1] * v[1]) / e.size ** 2
        if t < -eps / e.size or t > 1 + eps / e.size:
            return None
        t = min(1.0, max(0.0, t))
        return t if distance(point, point_at(e, t)) <= eps else None
    radius = distance(point, e.start)
    if abs(radius - e.size) > eps:
        return None
    angle = atan2(point[1] - e.start[1], point[0] - e.start[0]) % TAU
    if e.kind == "circle":
        return angle / TAU
    assert e.sweep_deg is not None
    start = atan2(e.end[1] - e.start[1], e.end[0] - e.start[0]) % TAU
    sweep = radians(e.sweep_deg)
    delta = (angle - start) % TAU if sweep > 0 else (start - angle) % TAU
    angular_eps = eps / e.size
    if delta <= abs(sweep) + angular_eps:
        return min(1.0, delta / abs(sweep))
    if TAU - delta <= angular_eps:
        return 0.0
    return None


def _angular_intervals(e: Entity) -> list[tuple[float, float]]:
    if e.kind == "circle":
        return [(0.0, TAU)]
    assert e.sweep_deg is not None
    start = atan2(e.end[1] - e.start[1], e.end[0] - e.start[0]) % TAU
    sweep = radians(e.sweep_deg)
    if sweep < 0:
        start = (start + sweep) % TAU
    finish = start + abs(sweep)
    return [(start, min(TAU, finish))] + ([(0.0, finish - TAU)] if finish > TAU else [])


def _coincident_circular(a: Entity, b: Entity) -> tuple[Point, ...]:
    threshold = NUMERIC_EPS_MM / max(a.size, b.size)
    for lo1, hi1 in _angular_intervals(a):
        for lo2, hi2 in _angular_intervals(b):
            if min(hi1, hi2) - max(lo1, lo2) > threshold:
                raise AmbiguousIntersectionError("Наложение дуг или окружностей на одной опорной окружности")
    result: list[Point] = []
    for point in (*endpoints(a), *endpoints(b)):
        if (parameter(a, point) is not None and parameter(b, point) is not None and
                not any(distance(point, prior) <= INTERSECTION_EPS_MM for prior in result)):
            result.append(point)
    return tuple(result)


def intersections(a: Entity, b: Entity) -> tuple[Point, ...]:
    """Пересечения ограниченных объектов. Наложение вызывает исключение."""
    possible: list[Point] = []
    if a.kind == "line" and b.kind == "line":
        r, s = _sub(a.end, a.start), _sub(b.end, b.start)
        q = _sub(b.start, a.start)
        denom = _cross(r, s)
        if abs(denom) <= 1e-12 * a.size * b.size:
            side0 = _cross(q, r) / a.size
            side1 = _cross(_sub(b.end, a.start), r) / a.size
            if side0 * side1 < 0 and max(abs(side0), abs(side1)) > INTERSECTION_EPS_MM:
                raise AmbiguousIntersectionError("Почти параллельные пересекающиеся отрезки")
            if abs(side0) <= INTERSECTION_EPS_MM:
                t0 = (q[0] * r[0] + q[1] * r[1]) / a.size ** 2
                q1 = _sub(b.end, a.start)
                t1 = (q1[0] * r[0] + q1[1] * r[1]) / a.size ** 2
                if (min(1.0, max(t0, t1)) - max(0.0, min(t0, t1))) * a.size > INTERSECTION_EPS_MM:
                    raise AmbiguousIntersectionError("Наложение отрезков")
                possible.extend(endpoints(a) + endpoints(b))
        else:
            t = _cross(q, s) / denom
            possible.append(point_at(a, t))
    elif a.kind == "line" or b.kind == "line":
        line, circle = (a, b) if a.kind == "line" else (b, a)
        vec = _sub(line.end, line.start)
        delta = _sub(line.start, circle.start)
        aa = line.size ** 2
        bb = 2 * (delta[0] * vec[0] + delta[1] * vec[1])
        cc = delta[0] ** 2 + delta[1] ** 2 - circle.size ** 2
        disc = bb * bb - 4 * aa * cc
        if disc < 0:
            # Near-tangencies within numerical noise are unsafe to classify as no cut.
            if disc > -4 * aa * INTERSECTION_EPS_MM * max(1.0, circle.size):
                raise AmbiguousIntersectionError("Почти касательное пересечение: требуется уточнить геометрию")
        else:
            root = sqrt(disc)
            possible.extend((point_at(line, (-bb - root) / (2 * aa)), point_at(line, (-bb + root) / (2 * aa))))
    else:
        dx, dy = _sub(b.start, a.start)
        d = hypot(dx, dy)
        if d <= INTERSECTION_EPS_MM and abs(a.size - b.size) <= INTERSECTION_EPS_MM:
            if d > NUMERIC_EPS_MM or abs(a.size - b.size) > NUMERIC_EPS_MM:
                raise AmbiguousIntersectionError("Почти совпадающие окружности или дуги")
            return _coincident_circular(a, b)
        if d <= INTERSECTION_EPS_MM:
            return ()
        if d > a.size + b.size or d < abs(a.size - b.size):
            gap = max(d - (a.size + b.size), abs(a.size - b.size) - d)
            if gap <= INTERSECTION_EPS_MM:
                raise AmbiguousIntersectionError("Почти касательные окружности или дуги")
            return ()
        along = (a.size ** 2 - b.size ** 2 + d ** 2) / (2 * d)
        h2 = a.size ** 2 - along ** 2
        if h2 < -INTERSECTION_EPS_MM * max(a.size, 1.0):
            raise AmbiguousIntersectionError("Неустойчивое пересечение окружностей")
        h = sqrt(max(0.0, h2))
        ux, uy = dx / d, dy / d
        base = (a.start[0] + along * ux, a.start[1] + along * uy)
        possible.extend(((base[0] - h * uy, base[1] + h * ux), (base[0] + h * uy, base[1] - h * ux)))
    result: list[Point] = []
    for point in possible:
        if (parameter(a, point) is not None and parameter(b, point) is not None and
                not any(distance(point, prior) <= INTERSECTION_EPS_MM for prior in result)):
            result.append(point)
    return tuple(result)


def arc_piece(e: Entity, t0: float, t1: float) -> Entity:
    from .sketch_draft import make_entity

    assert e.kind == "arc" and e.sweep_deg is not None
    return make_entity("arc", e.start, point_at(e, t0), e.sweep_deg * (t1 - t0))


def arc_length(e: Entity) -> float:
    assert e.kind == "arc" and e.sweep_deg is not None
    return e.size * abs(radians(e.sweep_deg))


def circle_remainder(e: Entity, start: float, end: float) -> Entity:
    """Остаток окружности после удаления участка start→end по CCW."""
    from .sketch_draft import make_entity

    assert e.kind == "circle"
    removed = (end - start) % 1.0
    return make_entity("arc", e.start, point_at(e, end), degrees(TAU * (1.0 - removed)))
