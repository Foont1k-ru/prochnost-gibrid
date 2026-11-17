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


def fillet_line_arc(line: Entity, arc: Entity, radius: float) -> tuple[tuple[Entity, Entity, Entity], ...]:
    """Кандидаты плавного сопряжения конечного отрезка и дуги с общим концом.

    Все возвращённые фигуры аналитические; касание и направление проверяются.
    Неоднозначный выбор остаётся пользователю. Вход не меняется.
    """
    from math import copysign, degrees, sqrt

    from .sketch_curves import NUMERIC_EPS_MM, endpoints
    from .sketch_draft import arc_end

    if line.kind != "line" or arc.kind != "arc":
        raise ValueError("Выберите отрезок и дугу")
    if not isfinite(radius) or radius < MIN_SIZE_MM:
        raise ValueError("Введите положительный радиус")
    matches = [(i, j) for i, a in enumerate(endpoints(line)) for j, b in enumerate(endpoints(arc))
               if distance(a, b) <= NUMERIC_EPS_MM]
    if len(matches) != 1:
        raise ValueError("Отрезок и дуга должны иметь ровно один общий конец")
    i, j = matches[0]
    corner = endpoints(line)[i]
    far = endpoints(line)[1 - i]
    ux, uy = (far[0] - corner[0]) / line.size, (far[1] - corner[1]) / line.size
    nx, ny = -uy, ux
    assert arc.sweep_deg is not None
    candidates: list[tuple[Entity, Entity, Entity]] = []
    for side in (-1, 1):
        # Centers of fillets lie on one of two offset lines.
        origin = (corner[0] + side * radius * nx, corner[1] + side * radius * ny)
        projection = (arc.start[0] - origin[0]) * ux + (arc.start[1] - origin[1]) * uy
        closest = (origin[0] + projection * ux, origin[1] + projection * uy)
        perpendicular = distance(closest, arc.start)
        for separation in (arc.size + radius, abs(arc.size - radius)):
            if separation <= NUMERIC_EPS_MM or perpendicular > separation + NUMERIC_EPS_MM:
                continue
            h2 = separation ** 2 - perpendicular ** 2
            if h2 < 0:
                h2 = 0
            for sign in (-1, 1):
                delta = sqrt(h2) * sign
                center = (closest[0] + delta * ux, closest[1] + delta * uy)
                along = (center[0] - corner[0]) * ux + (center[1] - corner[1]) * uy
                if not MIN_SIZE_MM < along < line.size - MIN_SIZE_MM:
                    continue
                p1 = (corner[0] + along * ux, corner[1] + along * uy)
                cx, cy = (center[0] - arc.start[0]) / separation, (center[1] - arc.start[1]) / separation
                for radial_sign in (-1, 1):
                    p2 = (arc.start[0] + radial_sign * arc.size * cx, arc.start[1] + radial_sign * arc.size * cy)
                    if abs(distance(p2, center) - radius) > max(1e-8, radius * 1e-10):
                        continue
                    t = parameter(arc, p2, eps=NUMERIC_EPS_MM)
                    if t is None or t * arc_length(arc) <= MIN_SIZE_MM or (1 - t) * arc_length(arc) <= MIN_SIZE_MM:
                        continue
                    a1 = degrees(atan2(p1[1] - center[1], p1[0] - center[0]))
                    a2 = degrees(atan2(p2[1] - center[1], p2[0] - center[0]))
                    sweep = (a2 - a1 + 180) % 360 - 180
                    if abs(sweep) < 1e-6:
                        continue
                    turn = copysign(1.0, sweep)
                    # Match traversal from line's far end to arc's far end, not a cusp.
                    t1 = (-turn * (p1[1] - center[1]) / radius, turn * (p1[0] - center[0]) / radius)
                    t2 = (-turn * (p2[1] - center[1]) / radius, turn * (p2[0] - center[0]) / radius)
                    arc_turn = copysign(1.0, arc.sweep_deg) * (1 if j == 0 else -1)
                    arc_tangent = (-arc_turn * (p2[1] - arc.start[1]) / arc.size,
                                   arc_turn * (p2[0] - arc.start[0]) / arc.size)
                    if t1[0] * -ux + t1[1] * -uy < 1 - 1e-8 or t2[0] * arc_tangent[0] + t2[1] * arc_tangent[1] < 1 - 1e-8:
                        continue
                    try:
                        new_line = make_entity("line", p1 if i == 0 else line.start, p1 if i == 1 else line.end)
                        new_arc = arc_piece(arc, t, 1) if j == 0 else arc_piece(arc, 0, t)
                        blend = make_entity("arc", center, p1, sweep)
                    except ValueError:
                        continue
                    if distance(arc_end(blend), p2) > max(NUMERIC_EPS_MM, radius * 1e-10):
                        continue
                    if not any(distance(center, candidate[2].start) <= NUMERIC_EPS_MM and
                               distance(p2, arc_end(candidate[2])) <= NUMERIC_EPS_MM for candidate in candidates):
                        candidates.append((new_line, new_arc, blend))
    return tuple(sorted(candidates, key=lambda pieces: (pieces[2].start, pieces[2].sweep_deg or 0)))


def fillet_arcs(first: Entity, second: Entity, radius: float) -> tuple[tuple[Entity, Entity, Entity], ...]:
    """Плавные сопряжения двух конечных дуг с одним общим концом."""
    from math import copysign, degrees, sqrt

    from .sketch_curves import NUMERIC_EPS_MM, endpoints
    from .sketch_draft import arc_end

    if first.kind != "arc" or second.kind != "arc":
        raise ValueError("Выберите две дуги")
    if not isfinite(radius) or radius < MIN_SIZE_MM:
        raise ValueError("Введите положительный радиус")
    matches = [(i, j) for i, a in enumerate(endpoints(first)) for j, b in enumerate(endpoints(second))
               if distance(a, b) <= NUMERIC_EPS_MM]
    if len(matches) != 1:
        raise ValueError("Дуги должны иметь ровно один общий конец")
    i, j = matches[0]
    center_distance = distance(first.start, second.start)
    if center_distance <= NUMERIC_EPS_MM:
        raise ValueError("Соосные дуги не поддерживаются для сопряжения")
    ux = (second.start[0] - first.start[0]) / center_distance
    uy = (second.start[1] - first.start[1]) / center_distance
    assert first.sweep_deg is not None and second.sweep_deg is not None
    candidates: list[tuple[Entity, Entity, Entity]] = []
    for d1 in (first.size + radius, abs(first.size - radius)):
        for d2 in (second.size + radius, abs(second.size - radius)):
            if min(d1, d2) <= NUMERIC_EPS_MM or center_distance > d1 + d2 + NUMERIC_EPS_MM or center_distance < abs(d1 - d2) - NUMERIC_EPS_MM:
                continue
            along = (d1 * d1 - d2 * d2 + center_distance * center_distance) / (2 * center_distance)
            h2 = d1 * d1 - along * along
            if h2 < -NUMERIC_EPS_MM * max(1.0, d1):
                continue
            h = sqrt(max(0.0, h2))
            for sign in (-1, 1):
                center = (first.start[0] + along * ux - sign * h * uy,
                          first.start[1] + along * uy + sign * h * ux)
                for s1, s2 in product((-1, 1), repeat=2):
                    p1 = (first.start[0] + s1 * first.size * (center[0] - first.start[0]) / d1,
                          first.start[1] + s1 * first.size * (center[1] - first.start[1]) / d1)
                    p2 = (second.start[0] + s2 * second.size * (center[0] - second.start[0]) / d2,
                          second.start[1] + s2 * second.size * (center[1] - second.start[1]) / d2)
                    if any(abs(distance(p, center) - radius) > max(NUMERIC_EPS_MM, radius * 1e-10) for p in (p1, p2)):
                        continue
                    t1 = parameter(first, p1, eps=NUMERIC_EPS_MM)
                    t2 = parameter(second, p2, eps=NUMERIC_EPS_MM)
                    if (t1 is None or t2 is None or min(t1, 1 - t1) * arc_length(first) <= MIN_SIZE_MM or
                            min(t2, 1 - t2) * arc_length(second) <= MIN_SIZE_MM):
                        continue
                    angle1 = degrees(atan2(p1[1] - center[1], p1[0] - center[0]))
                    angle2 = degrees(atan2(p2[1] - center[1], p2[0] - center[0]))
                    sweep = (angle2 - angle1 + 180) % 360 - 180
                    if abs(sweep) < 1e-6:
                        continue
                    turn = copysign(1.0, sweep)
                    v1 = (-turn * (p1[1] - center[1]) / radius, turn * (p1[0] - center[0]) / radius)
                    v2 = (-turn * (p2[1] - center[1]) / radius, turn * (p2[0] - center[0]) / radius)
                    turn1 = copysign(1.0, first.sweep_deg) * (-1 if i == 0 else 1)
                    turn2 = copysign(1.0, second.sweep_deg) * (1 if j == 0 else -1)
                    f1 = (-turn1 * (p1[1] - first.start[1]) / first.size,
                          turn1 * (p1[0] - first.start[0]) / first.size)
                    f2 = (-turn2 * (p2[1] - second.start[1]) / second.size,
                          turn2 * (p2[0] - second.start[0]) / second.size)
                    if v1[0] * f1[0] + v1[1] * f1[1] < 1 - 1e-8 or v2[0] * f2[0] + v2[1] * f2[1] < 1 - 1e-8:
                        continue
                    try:
                        new1 = arc_piece(first, t1, 1) if i == 0 else arc_piece(first, 0, t1)
                        new2 = arc_piece(second, t2, 1) if j == 0 else arc_piece(second, 0, t2)
                        blend = make_entity("arc", center, p1, sweep)
                    except ValueError:
                        continue
                    if distance(arc_end(blend), p2) > max(NUMERIC_EPS_MM, radius * 1e-10):
                        continue
                    if not any(distance(center, c[2].start) <= NUMERIC_EPS_MM and
                               distance(p1, c[2].end) <= NUMERIC_EPS_MM and
                               distance(p2, arc_end(c[2])) <= NUMERIC_EPS_MM for c in candidates):
                        candidates.append((new1, new2, blend))
    return tuple(sorted(candidates, key=lambda c: (c[2].start, c[2].sweep_deg or 0)))


def fillet_line_circle(line: Entity, circle: Entity, radius: float) -> tuple[tuple[Entity, Entity, Entity], ...]:
    """Варианты сопряжения по концу отрезка на окружности.

    Каждый вариант заменяет окружность дугой от точки касания до прежнего
    общего конца; этот конец остаётся открытым. Пользователь обязан выбрать
    вариант и подтвердить изменение топологии перед применением.
    """
    from math import copysign, degrees, sqrt

    from .sketch_curves import NUMERIC_EPS_MM, endpoints
    from .sketch_draft import arc_end

    if line.kind != "line" or circle.kind != "circle":
        raise ValueError("Выберите отрезок и окружность")
    if not isfinite(radius) or radius < MIN_SIZE_MM:
        raise ValueError("Введите положительный радиус")
    matches = [i for i, point in enumerate(endpoints(line)) if abs(distance(point, circle.start) - circle.size) <= NUMERIC_EPS_MM]
    if len(matches) != 1:
        raise ValueError("Ровно один конец отрезка должен лежать на окружности")
    i = matches[0]
    corner, far = endpoints(line)[i], endpoints(line)[1 - i]
    ux, uy = (far[0] - corner[0]) / line.size, (far[1] - corner[1]) / line.size
    nx, ny = -uy, ux
    start_angle = atan2(corner[1] - circle.start[1], corner[0] - circle.start[0])
    candidates: list[tuple[Entity, Entity, Entity]] = []
    for side in (-1, 1):
        origin = (corner[0] + side * radius * nx, corner[1] + side * radius * ny)
        projection = (circle.start[0] - origin[0]) * ux + (circle.start[1] - origin[1]) * uy
        closest = (origin[0] + projection * ux, origin[1] + projection * uy)
        perpendicular = distance(closest, circle.start)
        for separation in (circle.size + radius, abs(circle.size - radius)):
            if separation <= NUMERIC_EPS_MM or perpendicular > separation + NUMERIC_EPS_MM:
                continue
            h2 = max(0.0, separation ** 2 - perpendicular ** 2)
            for sign in (-1, 1):
                delta = sqrt(h2) * sign
                center = (closest[0] + delta * ux, closest[1] + delta * uy)
                along = (center[0] - corner[0]) * ux + (center[1] - corner[1]) * uy
                if not MIN_SIZE_MM < along < line.size - MIN_SIZE_MM:
                    continue
                p1 = (corner[0] + along * ux, corner[1] + along * uy)
                cx, cy = (center[0] - circle.start[0]) / separation, (center[1] - circle.start[1]) / separation
                for radial_sign in (-1, 1):
                    p2 = (circle.start[0] + radial_sign * circle.size * cx, circle.start[1] + radial_sign * circle.size * cy)
                    if abs(distance(p2, center) - radius) > max(NUMERIC_EPS_MM, radius * 1e-10):
                        continue
                    angle = atan2(p2[1] - circle.start[1], p2[0] - circle.start[0])
                    a1 = degrees(atan2(p1[1] - center[1], p1[0] - center[0]))
                    a2 = degrees(atan2(p2[1] - center[1], p2[0] - center[0]))
                    sweep = (a2 - a1 + 180) % 360 - 180
                    if abs(sweep) < 1e-6:
                        continue
                    turn = copysign(1.0, sweep)
                    t1 = (-turn * (p1[1] - center[1]) / radius, turn * (p1[0] - center[0]) / radius)
                    t2 = (-turn * (p2[1] - center[1]) / radius, turn * (p2[0] - center[0]) / radius)
                    if t1[0] * -ux + t1[1] * -uy < 1 - 1e-8:
                        continue
                    for circle_turn in (-1, 1):
                        removed = ((angle - start_angle) * circle_turn) % TAU
                        remaining = TAU - removed
                        if min(removed, remaining) * circle.size <= MIN_SIZE_MM:
                            continue
                        arc_tangent = (-circle_turn * (p2[1] - circle.start[1]) / circle.size,
                                       circle_turn * (p2[0] - circle.start[0]) / circle.size)
                        if t2[0] * arc_tangent[0] + t2[1] * arc_tangent[1] < 1 - 1e-8:
                            continue
                        try:
                            new_line = make_entity("line", p1 if i == 0 else line.start, p1 if i == 1 else line.end)
                            remainder = make_entity("arc", circle.start, p2, degrees(circle_turn * remaining))
                            blend = make_entity("arc", center, p1, sweep)
                        except ValueError:
                            continue
                        if (distance(arc_end(blend), p2) > max(NUMERIC_EPS_MM, radius * 1e-10) or
                                distance(arc_end(remainder), corner) > max(NUMERIC_EPS_MM, circle.size * 1e-12)):
                            continue
                        if not any(distance(center, c[2].start) <= NUMERIC_EPS_MM and
                                   distance(p2, c[1].end) <= NUMERIC_EPS_MM and
                                   abs((remainder.sweep_deg or 0) - (c[1].sweep_deg or 0)) < 1e-8 for c in candidates):
                            candidates.append((new_line, remainder, blend))
    return tuple(sorted(candidates, key=lambda c: (c[2].start, c[1].sweep_deg or 0)))
