"""Предварительная, ограниченная диагностика контуров из отрезков и окружностей.

Не исправляет геометрию, не строит тела и не заменяет проверку CAD-ядром.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite

from .sketch_curves import (
    NUMERIC_EPS_MM,
    AmbiguousIntersectionError,
    arc_length,
    distance,
    endpoints,
    intersections,
    parameter,
)
from .sketch_draft import Entity, Point, make_entity

MAX_CHECK_ENTITIES = 300
MAX_REPORTED_ISSUES = 100


@dataclass(frozen=True)
class ContourIssue:
    code: str
    message: str
    indices: tuple[int, ...]  # zero-based document indices
    points: tuple[Point, ...] = ()


@dataclass(frozen=True)
class ContourReport:
    tolerance: float
    issues: tuple[ContourIssue, ...]
    total_issues: int
    closed_loops: int | None


def _distance(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _minus(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _point_segment(point: Point, line: Entity) -> tuple[float, float]:
    x, y = _minus(line.end, line.start)
    px, py = _minus(point, line.start)
    t = (px * x + py * y) / (x * x + y * y)
    clipped = min(1.0, max(0.0, t))
    nearest = (line.start[0] + clipped * x, line.start[1] + clipped * y)
    return _distance(point, nearest), t


def _boxes_near(a: Entity, b: Entity, tolerance: float) -> bool:
    return not (max(a.start[0], a.end[0]) + tolerance < min(b.start[0], b.end[0]) or
                max(b.start[0], b.end[0]) + tolerance < min(a.start[0], a.end[0]) or
                max(a.start[1], a.end[1]) + tolerance < min(b.start[1], b.end[1]) or
                max(b.start[1], b.end[1]) + tolerance < min(a.start[1], a.end[1]))


def _line_conflict(a: Entity, b: Entity, tol: float) -> bool:
    if not _boxes_near(a, b, tol):
        return False
    r, s = _minus(a.end, a.start), _minus(b.end, b.start)
    delta = _minus(b.start, a.start)
    cross = _cross(r, s)
    # Collinear overlap, including almost-collinear segments within tolerance.
    d0 = abs(_cross(r, delta)) / a.size
    d1 = abs(_cross(r, _minus(b.end, a.start))) / a.size
    if d0 <= tol and d1 <= tol:
        t0 = (delta[0] * r[0] + delta[1] * r[1]) / a.size
        b_end = _minus(b.end, a.start)
        t1 = (b_end[0] * r[0] + b_end[1] * r[1]) / a.size
        overlap = min(a.size, max(t0, t1)) - max(0.0, min(t0, t1))
        if overlap > tol:
            return True
    if abs(cross) > 1e-14 * a.size * b.size:
        t, u = _cross(delta, s) / cross, _cross(delta, r) / cross
        if 0 <= t <= 1 and 0 <= u <= 1:
            # Only a shared endpoint is allowed; an interior crossing is not.
            at_a_end = min(t, 1 - t) * a.size <= tol
            at_b_end = min(u, 1 - u) * b.size <= tol
            if not (at_a_end and at_b_end):
                return True
    # T-junctions and near-contact of an endpoint with the other line interior.
    for point, other in ((a.start, b), (a.end, b), (b.start, a), (b.end, a)):
        distance, t = _point_segment(point, other)
        if distance <= tol and t * other.size > tol and (1 - t) * other.size > tol:
            return True
    return False


def _line_circle_conflict(line: Entity, circle: Entity, tol: float) -> bool:
    nearest, _ = _point_segment(circle.start, line)
    farthest = max(_distance(circle.start, line.start), _distance(circle.start, line.end))
    return nearest <= circle.size + tol and farthest >= circle.size - tol


def _circles_conflict(a: Entity, b: Entity, tol: float) -> bool:
    d = _distance(a.start, b.start)
    return d <= a.size + b.size + tol and d + min(a.size, b.size) >= max(a.size, b.size) - tol



def _distance_to_curve(point: Point, entity: Entity) -> float:
    if entity.kind == "line":
        return _point_segment(point, entity)[0]
    dx, dy = point[0] - entity.start[0], point[1] - entity.start[1]
    radius = hypot(dx, dy)
    if entity.kind == "circle":
        return abs(radius - entity.size)
    if radius > 0:
        on_circle = (entity.start[0] + entity.size * dx / radius, entity.start[1] + entity.size * dy / radius)
        if parameter(entity, on_circle) is not None:
            return abs(radius - entity.size)
    return min(distance(point, end) for end in endpoints(entity))


def _arc_pair_conflict(a: Entity, b: Entity, tol: float) -> bool:
    """Проверка конечных дуг; совпадение общих концов допускается."""
    try:
        points = intersections(a, b)
    except AmbiguousIntersectionError:
        return True
    a_ends, b_ends = endpoints(a), endpoints(b)

    def shared_endpoint(point: Point) -> bool:
        return (any(distance(point, p) <= NUMERIC_EPS_MM for p in a_ends) and
                any(distance(point, p) <= NUMERIC_EPS_MM for p in b_ends))

    if any(not shared_endpoint(point) for point in points):
        return True
    # Конец рядом с внутренней частью другой кривой — подозрительное касание.
    for point, other, other_ends in [(p, b, b_ends) for p in a_ends] + [(p, a, a_ends) for p in b_ends]:
        # Близкие концы отдельно показываются как разрыв, а не контакт.
        if _distance_to_curve(point, other) <= tol and not any(distance(point, end) <= tol for end in other_ends):
            return True
    # Близкое касание середины отрезка к внутренности дуги.
    if a.kind == "line" or b.kind == "line":
        line, curve = (a, b) if a.kind == "line" else (b, a)
        dx, dy = line.end[0] - line.start[0], line.end[1] - line.start[1]
        t = ((curve.start[0] - line.start[0]) * dx + (curve.start[1] - line.start[1]) * dy) / line.size ** 2
        if 0 <= t <= 1:
            projection = (line.start[0] + t * dx, line.start[1] + t * dy)
            dx, dy = projection[0] - curve.start[0], projection[1] - curve.start[1]
            length = hypot(dx, dy)
            if length > 0:
                radial = (curve.start[0] + curve.size * dx / length, curve.start[1] + curve.size * dy / length)
                if parameter(curve, radial) is not None and distance(projection, radial) <= tol and not shared_endpoint(radial):
                    return True
    else:
        # Центры задают направления ближайших точек двух опорных окружностей.
        dx, dy = b.start[0] - a.start[0], b.start[1] - a.start[1]
        length = hypot(dx, dy)
        if length > NUMERIC_EPS_MM:
            for sign in (-1, 1):
                for first, second, ux, uy in ((a, b, dx / length, dy / length), (b, a, -dx / length, -dy / length)):
                    point = (first.start[0] + sign * first.size * ux, first.start[1] + sign * first.size * uy)
                    if (parameter(first, point) is not None and _distance_to_curve(point, second) <= tol and
                            not shared_endpoint(point)):
                        return True
    return False

def check_contours(entities: tuple[Entity, ...], tolerance: float = 0.01) -> ContourReport:
    """Ищет открытые/близкие концы, ветвления, пересечения и касания.

    Точное совпадение точек и близость внутри допуска различаются; данные не
    объединяются. Ограничение размера защищает интерактивный интерфейс.
    """
    if len(entities) > MAX_CHECK_ENTITIES:
        raise ValueError(f"Проверка ограничена {MAX_CHECK_ENTITIES} элементами")
    if not isfinite(tolerance) or not 0.001 <= tolerance <= 1.0:
        raise ValueError("Допуск должен быть от 0,001 до 1 мм")
    for entity in entities:
        make_entity(entity.kind, entity.start, entity.end, entity.sweep_deg)
    found: list[ContourIssue] = []
    total = 0

    def add(code: str, message: str, indices: tuple[int, ...], points: tuple[Point, ...] = ()) -> None:
        nonlocal total
        total += 1
        if len(found) < MAX_REPORTED_ISSUES:
            found.append(ContourIssue(code, message, indices, points))

    if not entities:
        add("empty", "Эскиз не содержит элементов", ())
    # Лишь машинный шум (не пользовательский допуск) объединяет концы.
    vertices: list[tuple[list[Point], list[int]]] = []
    for index, entity in enumerate(entities):
        extent = arc_length(entity) if entity.kind == "arc" else entity.size
        if entity.size <= tolerance or extent <= tolerance:
            add("small", "Длина или радиус не больше допуска", (index,))
        for point in endpoints(entity):
            matching = [group for group in vertices if all(distance(point, p) <= NUMERIC_EPS_MM for p in group[0])]
            if len(matching) > 1:
                add("branch", "Неоднозначное совпадение точек", (index,), (point,))
            if matching:
                matching[0][0].append(point)
                matching[0][1].append(index)
            else:
                vertices.append(([point], [index]))
    for points, indices in vertices:
        point = points[0]
        if len(indices) == 1:
            near = [(other[0][0], other[1][0]) for other in vertices
                    if other[0] is not points and distance(point, other[0][0]) <= tolerance]
            if near:
                nearest, other_idx = min(near, key=lambda item: distance(point, item[0]))
                add("gap", f"Концы близко, но не совпадают: {distance(point, nearest):.6f} мм",
                    (indices[0], other_idx), (point, nearest))
            else:
                add("open", "Открытый конец элемента", (indices[0],), (point,))
        elif len(indices) != 2 or indices[0] == indices[1]:
            add("branch", "Ветвление или неоднозначное соединение концов", tuple(sorted(set(indices))), (point,))
    for i, a in enumerate(entities):
        for j in range(i + 1, len(entities)):
            b = entities[j]
            if a.kind == "arc" or b.kind == "arc":
                conflict = _arc_pair_conflict(a, b, tolerance)
            elif a.kind == "line" and b.kind == "line":
                conflict = _line_conflict(a, b, tolerance)
            elif a.kind == "circle" and b.kind == "circle":
                conflict = _circles_conflict(a, b, tolerance)
            else:
                conflict = _line_circle_conflict(a, b, tolerance) if a.kind == "line" else _line_circle_conflict(b, a, tolerance)
            if conflict:
                add("contact", "Пересечение, касание или наложение элементов", (i, j))
    loops: int | None = None
    if total == 0:
        # Each line vertex has degree 2 and pairwise contacts are clear.
        parent = list(range(len(entities)))

        def root(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for _points, indices in vertices:
            first, second = indices
            parent[root(first)] = root(second)
        loops = len({root(i) for i, entity in enumerate(entities) if entity.kind in ("line", "arc")})
        loops += sum(entity.kind == "circle" for entity in entities)
    return ContourReport(tolerance, tuple(found), total, loops)
