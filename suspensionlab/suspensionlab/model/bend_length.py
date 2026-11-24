"""Подбор длины осевой линии вдоль выбранного пользователем направления изгиба."""
from __future__ import annotations

import math

from .bent_tube import MAX_COORDINATE, MIN_SEGMENT, BentTubeError, Point3, make_bend_path


def vertex_for_length(start: Point3, end: Point3, vertex: Point3, radius: float,
                      tube_radius: float, length: float) -> Point3:
    """Оставляет продольную проекцию и сторону вершины, меняет только её высоту.

    Это одно из множества возможных решений, а не оптимизация конструкции. Длина
    относится к осевой линии до CAD-подрезок. Геометрия проверяется повторно.
    """
    path = make_bend_path(start, vertex, end, radius, tube_radius)
    if not math.isfinite(length) or length <= 0 or length > MAX_COORDINATE:
        raise BentTubeError('недопустимая длина')
    chord = math.dist(start, end)
    axis = tuple((end[i] - start[i]) / chord for i in range(3))
    along = sum((vertex[i] - start[i]) * axis[i] for i in range(3))
    if not MIN_SEGMENT < along < chord - MIN_SEGMENT:
        raise BentTubeError('проекция вершины должна находиться между опорами')
    foot = tuple(start[i] + along * axis[i] for i in range(3))
    height = math.dist(foot, vertex)
    if height < MIN_SEGMENT:
        raise BentTubeError('сначала задайте направление изгиба на проекции')
    direction = tuple((vertex[i] - foot[i]) / height for i in range(3))
    if length <= chord + 1e-7:
        raise BentTubeError('длина изгиба должна превышать расстояние между опорами; для прямой удалите вершину')
    if abs(length - path.length) < 1e-8:
        return vertex

    def evaluate(h: float) -> tuple[float, bool]:
        a, b = along, chord - along
        la, lb = math.hypot(a, h), math.hypot(b, h)
        sweep = math.atan2(h * chord, a * b - h * h)
        offset = radius * math.tan(sweep / 2)
        return la + lb - 2 * offset + radius * sweep, offset + MIN_SEGMENT <= min(la, lb)

    lo, hi = 0., height
    while True:
        value, fits = evaluate(hi)
        # For radii below half the chord, fitting can be lost and then restored:
        # an invalid intermediate height is not evidence that all later heights fail.
        if value >= length or hi >= MAX_COORDINATE or (not fits and radius >= chord / 2):
            break
        lo, hi = hi, min(hi * 2, MAX_COORDINATE)
    if not fits and radius >= chord / 2:
        # On this restricted branch, approach the first fitting limit from below.
        valid, invalid = lo, hi
        for _ in range(100):
            mid = (valid + invalid) / 2
            if evaluate(mid)[1]:
                valid = mid
            else:
                invalid = mid
        hi = valid
    if evaluate(hi)[0] < length - 1e-7:
        raise BentTubeError('не найден допустимый изгиб заданной длины при этом направлении и радиусе')
    for _ in range(100):
        mid = (lo + hi) / 2
        if evaluate(mid)[0] < length:
            lo = mid
        else:
            hi = mid
    result: Point3 = tuple(foot[i] + (lo + hi) / 2 * direction[i] for i in range(3))  # type: ignore[assignment]
    try:
        actual = make_bend_path(start, result, end, radius, tube_radius)
    except BentTubeError as error:
        raise BentTubeError('подобранный изгиб недопустим; измените направление, длину или радиус') from error
    if abs(actual.length - length) > max(1e-5, length * 1e-9):
        raise BentTubeError('не удалось точно подобрать длину')
    return result
