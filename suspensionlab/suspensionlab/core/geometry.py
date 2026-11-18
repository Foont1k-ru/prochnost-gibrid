"""Векторная геометрия, общая для всех типов подвесок.

Модуль не зависит от Qt. Внутренняя система координат — ISO 8855:
X вперёд, Y влево, Z вверх, начало — на уровне земли в плоскости
симметрии автомобиля. Знаки углов описаны в ``docs/formulas.md``.

Здесь собраны только элементарные операции (векторы, прямые, проекции,
углы). Кинематические решатели и метрики — в отдельных модулях.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Point3:
    """Точка в трёхмерном пространстве (мм)."""

    x: float
    y: float
    z: float

    def as_tuple(self) -> Vec3:
        """Возвращает координаты кортежем."""
        return (self.x, self.y, self.z)

    def __add__(self, other: Point3) -> Point3:
        return Point3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Point3) -> Point3:
        return Point3(self.x - other.x, self.y - other.y, self.z - other.z)

    def scaled(self, factor: float) -> Point3:
        """Умножение на скаляр."""
        return Point3(self.x * factor, self.y * factor, self.z * factor)

    def with_y(self, value: float) -> Point3:
        """Копия точки с другой координатой Y."""
        return Point3(self.x, value, self.z)


def v_add(a: Vec3, b: Vec3) -> Vec3:
    """Сложение векторов."""
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a: Vec3, b: Vec3) -> Vec3:
    """Разность векторов ``a - b``."""
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_scale(a: Vec3, k: float) -> Vec3:
    """Умножение вектора на скаляр."""
    return (a[0] * k, a[1] * k, a[2] * k)


def v_dot(a: Vec3, b: Vec3) -> float:
    """Скалярное произведение."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a: Vec3, b: Vec3) -> Vec3:
    """Векторное произведение."""
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def v_norm(a: Vec3) -> float:
    """Длина вектора."""
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def v_normalize(a: Vec3) -> Vec3:
    """Единичный вектор; для нулевого вектора возвращает ``(0, 0, 0)``."""
    length = v_norm(a)
    if length < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / length, a[1] / length, a[2] / length)


def distance(a: Vec3, b: Vec3) -> float:
    """Расстояние между точками."""
    return v_norm(v_sub(a, b))


def midpoint(a: Vec3, b: Vec3) -> Vec3:
    """Середина отрезка."""
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0)


def mirror_y(p: Vec3) -> Vec3:
    """Зеркальное отражение точки относительно плоскости симметрии (Y = 0)."""
    return (p[0], -p[1], p[2])


def distance_point_to_line(p: Vec3, a: Vec3, b: Vec3) -> float:
    """Расстояние от точки ``p`` до прямой, проходящей через ``a`` и ``b``."""
    direction = v_sub(b, a)
    length = v_norm(direction)
    if length < 1e-9:
        return distance(p, a)
    unit = v_scale(direction, 1.0 / length)
    rel = v_sub(p, a)
    along = v_dot(rel, unit)
    perpendicular = v_sub(rel, v_scale(unit, along))
    return v_norm(perpendicular)


def closest_point_on_line(p: Vec3, a: Vec3, b: Vec3) -> Vec3:
    """Проекция точки на прямую (не отрезок)."""
    direction = v_sub(b, a)
    length_sq = v_dot(direction, direction)
    if length_sq < 1e-12:
        return a
    t = v_dot(v_sub(p, a), direction) / length_sq
    return v_add(a, v_scale(direction, t))


def axis_length(points: list[Vec3]) -> float:
    """Расстояние от последней точки до прямой через остальные точки.

    Используется для «длины рычага»: у A-образного рычага длина считается
    от оси качания (две внутренние точки) до наружной шаровой, а не от
    произвольной внутренней точки.
    """
    if len(points) < 2:
        return 0.0
    end = points[-1]
    if len(points) == 2:
        return distance(end, points[0])
    return distance_point_to_line(end, points[0], points[1])


def angle_between(a: Vec3, b: Vec3) -> float:
    """Угол между векторами в градусах (0…180)."""
    na, nb = v_norm(a), v_norm(b)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    cosine = max(-1.0, min(1.0, v_dot(a, b) / (na * nb)))
    return math.degrees(math.acos(cosine))


def link_plan_angle(a: Vec3, b: Vec3) -> float:
    """Угол рычага в плане (вид сверху) к продольной оси, градусы.

    Положительный угол — наружный конец отклонён назад (к отрицательному X).
    """
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return 0.0
    return math.degrees(math.atan2(-dy, -dx))


def link_side_angle(a: Vec3, b: Vec3) -> float:
    """Угол рычага в боковой проекции к горизонтали, градусы.

    Положительный угол — наружный конец выше внутреннего.
    """
    dx = b[0] - a[0]
    dz = b[2] - a[2]
    horizontal = math.hypot(dx, b[1] - a[1])
    if abs(horizontal) < 1e-12 and abs(dz) < 1e-12:
        return 0.0
    return math.degrees(math.atan2(dz, horizontal))


def wrap_deg_180(angle: float) -> float:
    """Приводит угол к диапазону (−180, 180]."""
    result = math.fmod(angle + 180.0, 360.0)
    if result <= 0.0:
        result += 360.0
    return result - 180.0


def intersect_lines_2d(a1: Vec2, a2: Vec2, b1: Vec2, b2: Vec2) -> Vec2 | None:
    """Пересечение двух прямых на плоскости (None — прямые параллельны)."""
    dax = a2[0] - a1[0]
    day = a2[1] - a1[1]
    dbx = b2[0] - b1[0]
    dby = b2[1] - b1[1]
    denominator = dax * dby - day * dbx
    if abs(denominator) < 1e-9:
        return None
    t = ((b1[0] - a1[0]) * dby - (b1[1] - a1[1]) * dbx) / denominator
    return (a1[0] + t * dax, a1[1] + t * day)


def circle_center_radius_through(p1: Vec2, p2: Vec2, radius: float) -> Vec2 | None:
    """Центр окружности радиуса ``radius``, проходящей через две точки.

    Используется при решении положения кулака: точка кулака лежит на
    окружности вокруг оси рычага. Возвращает центр, ближайший к
    положительному направлению (выбирается внешней логикой).
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    chord = math.hypot(dx, dy)
    if chord < 1e-9 or chord > 2.0 * radius:
        return None
    mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    h = math.sqrt(max(0.0, radius * radius - (chord / 2.0) ** 2))
    ux, uy = -dy / chord, dx / chord
    return (mid[0] + ux * h, mid[1] + uy * h)
