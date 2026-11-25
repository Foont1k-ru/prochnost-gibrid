"""Ближайшие точки двух отрезков и условные капсулы вокруг их осей.

Это расчёт простых геометрических ограничений в отдельных позах, не CAD и не
проверка всей подвески. Размеры капсул должны быть заданы вызывающим кодом.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import dist, isfinite

Point = tuple[float, float, float]
_MAX_COORDINATE = 1_000_000.0


def _point(value: Point) -> Point:
    if (not isinstance(value, (tuple, list)) or len(value) != 3 or
            any(type(v) not in (int, float) or not isfinite(v) or abs(v) > _MAX_COORDINATE for v in value)):
        raise ValueError('Некорректные координаты отрезка')
    return float(value[0]), float(value[1]), float(value[2])


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _add_scaled(a: Point, b: Point, t: float) -> Point:
    return a[0] + b[0] * t, a[1] + b[1] * t, a[2] + b[2] * t


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Point, b: Point) -> Point:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _clamp(value: float) -> float:
    return max(0., min(1., value))


@dataclass(frozen=True, slots=True)
class ClosestSegments:
    distance_mm: float
    first: Point
    second: Point
    first_parameter: float
    second_parameter: float


def closest_segments(a: Point, b: Point, c: Point, d: Point) -> ClosestSegments:
    """Точный минимум двух *конечных* отрезков в пределах точности float64.

    Рассматриваются четыре границы и внутренняя стационарная точка; это не
    выборка по длине. Вырожденные отрезки обрабатываются как точки. При почти
    параллельных направлениях используется векторное произведение, а не
    вычитание двух почти равных квадратов. Большой динамический диапазон и
    округление ограничивают численную точность.
    """
    a, b, c, d = _point(a), _point(b), _point(c), _point(d)
    u, v, w = _sub(b, a), _sub(d, c), _sub(a, c)
    aa, cc = _dot(u, u), _dot(v, v)
    candidates: list[tuple[float, float]] = []
    if cc > 0:
        candidates.extend(((0., _clamp(_dot(v, w) / cc)),
                           (1., _clamp(_dot(v, _sub(b, c)) / cc))))
    else:
        candidates.extend(((0., 0.), (1., 0.)))
    if aa > 0:
        candidates.extend(((_clamp(-_dot(u, w) / aa), 0.),
                           (_clamp(_dot(u, _sub(d, a)) / aa), 1.)))
    else:
        candidates.extend(((0., 0.), (0., 1.)))
    cross = _cross(u, v)
    determinant = _dot(cross, cross)
    if determinant > 0:
        s = _dot(_cross(v, w), cross) / determinant
        t = _dot(_cross(u, w), cross) / determinant
        if isfinite(s) and isfinite(t) and 0 <= s <= 1 and 0 <= t <= 1:
            candidates.append((s, t))
    best_s, best_t = min(candidates, key=lambda pair: dist(_add_scaled(a, u, pair[0]),
                                                            _add_scaled(c, v, pair[1])))
    first, second = _add_scaled(a, u, best_s), _add_scaled(c, v, best_t)
    distance = dist(first, second)
    if not isfinite(distance):
        raise ValueError('Расстояние не является конечным')
    return ClosestSegments(distance, first, second, best_s, best_t)


@dataclass(frozen=True, slots=True)
class CapsuleClearance:
    axes: ClosestSegments
    clearance_mm: float
    status: str


def capsule_clearance(a: Point, b: Point, radius_a: float, c: Point, d: Point,
                      radius_b: float, required_clearance_mm: float) -> CapsuleClearance:
    """Условный зазор между двумя капсулами; отрицательный означает наложение.

    Капсула состоит из цилиндра между центрами и сферических концов. Радиусы
    и заданный запас — вход пользователя, не реальные размеры детали и не
    подтверждение совместимости. Соприкосновение считается требующим внимания.
    """
    for radius in (radius_a, radius_b):
        if type(radius) not in (int, float) or not isfinite(radius) or not 0 < radius <= _MAX_COORDINATE:
            raise ValueError('Радиус должен быть конечным и положительным')
    if (type(required_clearance_mm) not in (int, float) or not isfinite(required_clearance_mm) or
            not 0 <= required_clearance_mm <= _MAX_COORDINATE):
        raise ValueError('Запас должен быть конечным и неотрицательным')
    axes = closest_segments(a, b, c, d)
    clearance = axes.distance_mm - radius_a - radius_b
    tolerance = 1e-6
    if clearance < -tolerance:
        status = 'overlap'
    elif clearance <= tolerance:
        status = 'touch'
    elif clearance < required_clearance_mm - tolerance:
        status = 'low_clearance'
    elif required_clearance_mm > 0 and abs(clearance - required_clearance_mm) <= tolerance:
        status = 'limit'
    else:
        status = 'clear'
    return CapsuleClearance(axes, clearance, status)
