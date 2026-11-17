"""Одноразовые построения касательных окружностей и обрезка отрезков."""
from __future__ import annotations

from itertools import product
from math import atan2, hypot, isfinite, radians

from .sketch_curves import TAU, arc_length, arc_piece, circle_remainder, distance, intersections, parameter, point_at
from .sketch_draft import MIN_SIZE_MM, Entity, Point, make_entity


def _line_data(line: Entity) -> tuple[float, float, float]:
    if line.kind != "line":
        raise ValueError("Выбирайте только отрезки")
    dx, dy = line.end[0] - line.start[0], line.end[1] - line.start[1]
    length = hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    return nx, ny, nx * line.start[0] + ny * line.start[1]


def _solve(rows: list[list[float]], values: list[float]) -> list[float] | None:
    n = len(values)
    mat = [row[:] + [values[i]] for i, row in enumerate(rows)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda i: abs(mat[i][col]))
        if abs(mat[pivot][col]) < 1e-10:
            return None
        mat[col], mat[pivot] = mat[pivot], mat[col]
        value = mat[col][col]
        for k in range(col, n + 1):
            mat[col][k] /= value
        for i in range(n):
            if i == col:
                continue
            factor = mat[i][col]
            for k in range(col, n + 1):
                mat[i][k] -= factor * mat[col][k]
    return [row[-1] for row in mat]


def tangent_circles(lines: tuple[Entity, ...], radius: float | None = None) -> tuple[Entity, ...]:
    """Касание только к конечным отрезкам; результата может быть несколько.

    Для двух отрезков задаётся радиус, для трёх вычисляется. Параллельные
    системы с бесконечным числом решений не возвращаются.
    """
    if len(lines) not in (2, 3):
        raise ValueError("Нужно выбрать два или три отрезка")
    if len(lines) == 2 and (radius is None or not isfinite(radius) or radius < MIN_SIZE_MM):
        raise ValueError("Введите положительный радиус")
    data = [_line_data(line) for line in lines]
    results: list[Entity] = []
    for signs in product((-1, 1), repeat=len(lines)):
        if len(lines) == 2:
            assert radius is not None
            solution = _solve([[nx, ny] for nx, ny, _ in data],
                              [c + sign * radius for (_, _, c), sign in zip(data, signs, strict=True)])
            if solution is None:
                continue
            x, y = solution
            r = radius
        else:
            solution = _solve([[nx, ny, -float(sign)] for (nx, ny, _), sign in zip(data, signs, strict=True)],
                              [c for _, _, c in data])
            if solution is None:
                continue
            x, y, r = solution
            if r < MIN_SIZE_MM:
                continue
        if not all(isfinite(v) for v in (x, y, r)):
            continue
        feet: list[Point] = []
        for line, (nx, ny, c) in zip(lines, data, strict=True):
            dist = nx * x + ny * y - c
            foot = (x - dist * nx, y - dist * ny)
            dx, dy = line.end[0] - line.start[0], line.end[1] - line.start[1]
            t = ((foot[0] - line.start[0]) * dx + (foot[1] - line.start[1]) * dy) / (line.size ** 2)
            if t < -1e-9 or t > 1 + 1e-9 or abs(abs(dist) - r) > max(1e-6, r * 1e-9):
                break
            feet.append(foot)
        if len(feet) != len(lines):
            continue
        try:
            candidate = make_entity("circle", (x, y), feet[0])
        except ValueError:
            continue
        if not any(hypot(c.start[0] - x, c.start[1] - y) < 1e-6 and abs(c.size - r) < 1e-6 for c in results):
            results.append(candidate)
    return tuple(sorted(results, key=lambda e: (e.size, e.start)))



def _click_parameter(entity: Entity, click: Point) -> float:
    if entity.kind == "line":
        dx, dy = entity.end[0] - entity.start[0], entity.end[1] - entity.start[1]
        return max(0.0, min(1.0, ((click[0] - entity.start[0]) * dx + (click[1] - entity.start[1]) * dy) / entity.size ** 2))
    angle = atan2(click[1] - entity.start[1], click[0] - entity.start[0]) % TAU
    if entity.kind == "circle":
        return angle / TAU
    assert entity.sweep_deg is not None
    start = atan2(entity.end[1] - entity.start[1], entity.end[0] - entity.start[0]) % TAU
    sweep = radians(entity.sweep_deg)
    delta = (angle - start) % TAU if sweep > 0 else (start - angle) % TAU
    if delta <= abs(sweep):
        return delta / abs(sweep)
    return 0.0 if distance(click, point_at(entity, 0)) <= distance(click, point_at(entity, 1)) else 1.0


def trim_entity(entities: tuple[Entity, ...], index: int, clicked: Point) -> tuple[Entity, ...]:
    """Удалить участок линии, дуги или окружности между соседними пересечениями.

    Все режущие элементы конечны. Неоднозначные наложения блокируют операцию.
    Возвращает новые аналитические элементы, не изменяя исходный документ.
    """
    if index < 0 or index >= len(entities):
        raise ValueError("Выберите элемент для обрезки")
    target = entities[index]
    extent = arc_length(target) if target.kind == "arc" else (target.size * TAU if target.kind == "circle" else target.size)
    epsilon = max(1e-10, MIN_SIZE_MM / extent)
    cuts: list[float] = []
    for i, other in enumerate(entities):
        if i == index:
            continue
        for point in intersections(target, other):
            t = parameter(target, point)
            if t is not None and (target.kind == "circle" or epsilon < t < 1 - epsilon):
                cuts.append(t)
    cuts.sort()
    unique: list[float] = []
    for cut in cuts:
        if not unique or cut - unique[-1] > epsilon:
            unique.append(cut)
    if target.kind == "circle" and len(unique) > 1 and 1 - unique[-1] + unique[0] <= epsilon:
        unique.pop()
    needed = 2 if target.kind == "circle" else 1
    if len(unique) < needed:
        raise ValueError("Недостаточно внутренних пересечений для обрезки")
    selected = _click_parameter(target, clicked)
    if any((min(abs(selected - cut), 1 - abs(selected - cut)) if target.kind == "circle" else abs(selected - cut))
           <= epsilon for cut in unique):
        raise ValueError("Укажите участок между пересечениями, не саму точку")
    if target.kind == "circle":
        for i, start in enumerate(unique):
            end = unique[(i + 1) % len(unique)]
            if (selected - start) % 1.0 < (end - start) % 1.0:
                return (circle_remainder(target, start, end),)
        raise ValueError("Не удалось определить участок окружности")
    bounds = [0.0, *unique, 1.0]
    interval = next(i for i in range(len(bounds) - 1) if bounds[i] <= selected <= bounds[i + 1])
    parts: list[Entity] = []
    if bounds[interval] > epsilon:
        if target.kind == "line":
            parts.append(make_entity("line", target.start, point_at(target, bounds[interval])))
        else:
            parts.append(arc_piece(target, 0, bounds[interval]))
    if bounds[interval + 1] < 1 - epsilon:
        if target.kind == "line":
            parts.append(make_entity("line", point_at(target, bounds[interval + 1]), target.end))
        else:
            parts.append(arc_piece(target, bounds[interval + 1], 1))
    return tuple(parts)


def trim_line(entities: tuple[Entity, ...], index: int, clicked: Point) -> tuple[Entity, ...]:
    if index < 0 or index >= len(entities) or entities[index].kind != "line":
        raise ValueError("Для обрезки выберите отрезок")
    return trim_entity(entities, index, clicked)


def trim_circle(entities: tuple[Entity, ...], index: int, clicked: Point) -> tuple[Entity, ...]:
    if index < 0 or index >= len(entities) or entities[index].kind != "circle":
        raise ValueError("Для обрезки выберите окружность")
    return trim_entity(entities, index, clicked)


def fillet_lines(first: Entity, second: Entity, radius: float) -> tuple[Entity, Entity, Entity]:
    """Скругление двух отрезков, имеющих общий конец. Результат не меняет вход."""
    from math import acos, atan2, degrees, sin, tan

    from .sketch_curves import NUMERIC_EPS_MM

    if first.kind != "line" or second.kind != "line":
        raise ValueError("Сопряжение пока доступно только для двух отрезков")
    if not isfinite(radius) or radius < MIN_SIZE_MM:
        raise ValueError("Введите положительный радиус")
    matches = [(i, j) for i, a in enumerate((first.start, first.end)) for j, b in enumerate((second.start, second.end))
               if distance(a, b) <= NUMERIC_EPS_MM]
    if len(matches) != 1:
        raise ValueError("Отрезки должны иметь ровно один общий конец")
    i, j = matches[0]
    corner = (first.start, first.end)[i]
    far1, far2 = (first.end, first.start)[i], (second.end, second.start)[j]
    length1, length2 = distance(corner, far1), distance(corner, far2)
    u = ((far1[0] - corner[0]) / length1, (far1[1] - corner[1]) / length1)
    v = ((far2[0] - corner[0]) / length2, (far2[1] - corner[1]) / length2)
    dot = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
    theta = acos(dot)
    cross = u[0] * v[1] - u[1] * v[0]
    if abs(cross) < 1e-9 or theta < 1e-9:
        raise ValueError("Параллельные или почти параллельные отрезки не скругляются")
    setback = radius / tan(theta / 2)
    if not isfinite(setback) or min(length1, length2) - setback < MIN_SIZE_MM:
        raise ValueError("Радиус слишком велик для длины отрезков")
    p1 = (corner[0] + u[0] * setback, corner[1] + u[1] * setback)
    p2 = (corner[0] + v[0] * setback, corner[1] + v[1] * setback)
    bisector_length = hypot(u[0] + v[0], u[1] + v[1])
    center_distance = radius / sin(theta / 2)
    center = (corner[0] + (u[0] + v[0]) / bisector_length * center_distance,
              corner[1] + (u[1] + v[1]) / bisector_length * center_distance)
    angle1 = degrees(atan2(p1[1] - center[1], p1[0] - center[0]))
    angle2 = degrees(atan2(p2[1] - center[1], p2[0] - center[0]))
    sweep = (angle2 - angle1 + 180) % 360 - 180
    new1 = make_entity("line", p1 if i == 0 else first.start, p1 if i == 1 else first.end)
    new2 = make_entity("line", p2 if j == 0 else second.start, p2 if j == 1 else second.end)
    arc = make_entity("arc", center, p1, sweep)
    from .sketch_draft import arc_end

    if distance(arc_end(arc), p2) > max(1e-8, radius * 1e-10):
        raise ValueError("Не удалось точно построить сопряжение")
    return new1, new2, arc
