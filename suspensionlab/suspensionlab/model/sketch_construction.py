"""Одноразовые построения касательных окружностей и обрезка отрезков."""
from __future__ import annotations

from itertools import product
from math import hypot, isfinite, sqrt

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


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def trim_line(entities: tuple[Entity, ...], index: int, clicked: Point) -> tuple[Entity, ...]:
    """Удаляет часть выбранного отрезка между ближайшими пересечениями.

    Только отрезки обрезаются, границы — конечные отрезки и полные окружности.
    Коллинеарное наложение и дуги отклоняются как неоднозначные случаи.
    """
    if index < 0 or index >= len(entities) or entities[index].kind != "line":
        raise ValueError("Для обрезки выберите отрезок")
    if any(e.kind == "arc" for e in entities):
        raise ValueError("Обрезка эскиза с дугами пока не поддерживается")
    target = entities[index]
    r = _sub(target.end, target.start)
    length = target.size
    cuts: list[float] = []
    eps = max(1e-10, MIN_SIZE_MM / length)
    for i, other in enumerate(entities):
        if i == index:
            continue
        if other.kind == "line":
            s = _sub(other.end, other.start)
            q = _sub(other.start, target.start)
            cross = _cross(r, s)
            if abs(cross) <= 1e-12 * length * other.size:
                if abs(_cross(q, r)) / length <= 1e-7:
                    t0 = (q[0] * r[0] + q[1] * r[1]) / (length * length)
                    q1 = _sub(other.end, target.start)
                    t1 = (q1[0] * r[0] + q1[1] * r[1]) / (length * length)
                    if min(1, max(t0, t1)) - max(0, min(t0, t1)) > eps:
                        raise ValueError("Обрезка неоднозначна: наложение отрезков")
                continue
            t, u = _cross(q, s) / cross, _cross(q, r) / cross
            if eps < t < 1 - eps and -eps <= u <= 1 + eps:
                cuts.append(t)
        else:
            delta = _sub(target.start, other.start)
            aa = length * length
            bb = 2 * (delta[0] * r[0] + delta[1] * r[1])
            cc = delta[0] ** 2 + delta[1] ** 2 - other.size ** 2
            disc = bb * bb - 4 * aa * cc
            if disc < 0:
                continue
            root = sqrt(disc)
            cuts.extend(t for t in ((-bb - root) / (2 * aa), (-bb + root) / (2 * aa)) if eps < t < 1 - eps)
    cuts.sort()
    unique: list[float] = []
    for value in cuts:
        if not unique or value - unique[-1] > eps:
            unique.append(value)
    if not unique:
        raise ValueError("На отрезке нет внутренних пересечений")
    d = _sub(clicked, target.start)
    at = max(0.0, min(1.0, (d[0] * r[0] + d[1] * r[1]) / (length * length)))
    if any(abs(at - cut) <= eps for cut in unique):
        raise ValueError("Укажите участок между пересечениями, не саму точку")
    bounds = [0.0, *unique, 1.0]
    selected = next(i for i in range(len(bounds) - 1) if bounds[i] <= at <= bounds[i + 1])

    def point(t: float) -> Point:
        return target.start[0] + t * r[0], target.start[1] + t * r[1]

    parts: list[Entity] = []
    if bounds[selected] > eps:
        parts.append(make_entity("line", target.start, point(bounds[selected])))
    if bounds[selected + 1] < 1 - eps:
        parts.append(make_entity("line", point(bounds[selected + 1]), target.end))
    return tuple(parts)


def trim_circle(entities: tuple[Entity, ...], index: int, clicked: Point) -> tuple[Entity, ...]:
    """Удаляет дугу полной окружности между соседними пересечениями.

    Другие дуги пока не являются режущими объектами; при их наличии операция
    отклоняется, чтобы не пропустить границу и не удалить неверный участок.
    """
    from math import atan2, cos, degrees, pi, sin

    if index < 0 or index >= len(entities) or entities[index].kind != "circle":
        raise ValueError("Для обрезки выберите полную окружность")
    if any(e.kind == "arc" for e in entities):
        raise ValueError("Обрезка эскиза с дугами пока не поддерживается")
    circle = entities[index]
    center = circle.start
    radius = circle.size
    angles: list[float] = []
    eps = max(1e-10, MIN_SIZE_MM / radius)

    def push(point: Point) -> None:
        angles.append(atan2(point[1] - center[1], point[0] - center[0]) % (2 * pi))

    for i, other in enumerate(entities):
        if i == index:
            continue
        if other.kind == "line":
            vector = _sub(other.end, other.start)
            delta = _sub(other.start, center)
            aa = other.size ** 2
            bb = 2 * (delta[0] * vector[0] + delta[1] * vector[1])
            cc = delta[0] ** 2 + delta[1] ** 2 - radius ** 2
            disc = bb * bb - 4 * aa * cc
            if disc < 0:
                continue
            root = sqrt(disc)
            for t in ((-bb - root) / (2 * aa), (-bb + root) / (2 * aa)):
                if 0 <= t <= 1:
                    push((other.start[0] + t * vector[0], other.start[1] + t * vector[1]))
        else:
            dx, dy = _sub(other.start, center)
            distance = hypot(dx, dy)
            r2 = other.size
            if distance < 1e-9:
                if abs(radius - r2) < 1e-7:
                    raise ValueError("Обрезка неоднозначна: окружности совпадают")
                continue
            if distance > radius + r2 or distance < abs(radius - r2):
                continue
            along = (radius * radius - r2 * r2 + distance * distance) / (2 * distance)
            height_sq = radius * radius - along * along
            if height_sq < -1e-6:
                continue
            height = sqrt(max(0.0, height_sq))
            ux, uy = dx / distance, dy / distance
            base = (center[0] + along * ux, center[1] + along * uy)
            push((base[0] - height * uy, base[1] + height * ux))
            push((base[0] + height * uy, base[1] - height * ux))
    angles.sort()
    unique: list[float] = []
    for angle in angles:
        if not unique or angle - unique[-1] > eps:
            unique.append(angle)
    if len(unique) > 1 and 2 * pi - unique[-1] + unique[0] <= eps:
        unique.pop()
    if len(unique) < 2:
        raise ValueError("Для обрезки окружности нужны минимум два разных пересечения")
    chosen = atan2(clicked[1] - center[1], clicked[0] - center[0]) % (2 * pi)
    if any(min((chosen - a) % (2 * pi), (a - chosen) % (2 * pi)) <= eps for a in unique):
        raise ValueError("Укажите участок между пересечениями, не саму точку")
    for i, start in enumerate(unique):
        end = unique[(i + 1) % len(unique)]
        span = (end - start) % (2 * pi)
        if (chosen - start) % (2 * pi) < span:
            # The remainder starts at the end of the removed interval and goes CCW.
            initial = (center[0] + radius * cos(end), center[1] + radius * sin(end))
            return (make_entity("arc", center, initial, degrees(2 * pi - span)),)
    raise ValueError("Не удалось определить участок окружности")


def trim_entity(entities: tuple[Entity, ...], index: int, clicked: Point) -> tuple[Entity, ...]:
    if 0 <= index < len(entities) and entities[index].kind == "circle":
        return trim_circle(entities, index, clicked)
    return trim_line(entities, index, clicked)
