"""Независимый черновик по трём точкам, без проекта и расчётного снимка.

Осевая линия — предварительная геометрия, не подтверждение кинематики, зазоров,
сварки, технологичности или прочности. Общая среда не ограничена двумя трубами;
этот частный документ описывает только существующий инструмент рычага.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .bent_tube import BentTubeError, Point3, make_bend_path

MAX_COORDINATE_MM = 1_000_000.0
MIN_LENGTH_MM = 0.01
MAX_TUBE_MM = 10_000.0


class FreeArmError(ValueError):
    """Неподдерживаемые данные независимого черновика."""


def _number(value: Any, low: float, high: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FreeArmError(f'{label}: требуется число')
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise FreeArmError(f'{label}: число вне диапазона') from error
    if not math.isfinite(number) or not low <= number <= high:
        raise FreeArmError(f'{label}: число вне диапазона')
    return number


def _point(value: Any, label: str) -> Point3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise FreeArmError(f'{label}: требуется три координаты')
    return tuple(_number(x, -MAX_COORDINATE_MM, MAX_COORDINATE_MM, label) for x in value)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class FreeArmBend:
    """Одна явно заданная вершина и радиус, координаты в системе черновика."""

    vertex_mm: Point3
    radius_mm: float

    def __post_init__(self) -> None:
        object.__setattr__(self, 'vertex_mm', _point(self.vertex_mm, 'Вершина изгиба'))
        object.__setattr__(self, 'radius_mm', _number(self.radius_mm, MIN_LENGTH_MM, MAX_COORDINATE_MM,
                                                     'Радиус изгиба'))


@dataclass(frozen=True, slots=True)
class FreeArmDraft:
    """Независимые опоры: передняя, задняя и общая наружная, в мм.

    У объекта нет проекта, ссылки на подвеску или заявленного результата расчёта.
    Все поля неизменяемы, для редактирования создаётся и проверяется новый объект.
    """

    front_mm: Point3
    rear_mm: Point3
    outer_mm: Point3
    radius_mm: float
    wall_mm: float
    front_bend: FreeArmBend | None = None
    rear_bend: FreeArmBend | None = None

    def __post_init__(self) -> None:
        for field, label in (('front_mm', 'Передняя опора'), ('rear_mm', 'Задняя опора'),
                             ('outer_mm', 'Наружная опора')):
            object.__setattr__(self, field, _point(getattr(self, field), label))
        radius = _number(self.radius_mm, MIN_LENGTH_MM, MAX_TUBE_MM, 'Радиус трубы')
        wall = _number(self.wall_mm, MIN_LENGTH_MM, MAX_TUBE_MM, 'Толщина стенки')
        if radius - wall < MIN_LENGTH_MM:
            raise FreeArmError('Толщина стенки должна оставлять положительный внутренний радиус')
        object.__setattr__(self, 'radius_mm', radius)
        object.__setattr__(self, 'wall_mm', wall)
        points = (self.front_mm, self.rear_mm, self.outer_mm)
        if any(math.dist(points[i], points[j]) < MIN_LENGTH_MM for i, j in ((0, 1), (0, 2), (1, 2))):
            raise FreeArmError('Опорные точки совпадают или расположены слишком близко')
        for start, bend in ((self.front_mm, self.front_bend), (self.rear_mm, self.rear_bend)):
            if bend is not None:
                if not isinstance(bend, FreeArmBend):
                    raise FreeArmError('Неверные параметры изгиба')
                try:
                    make_bend_path(start, bend.vertex_mm, self.outer_mm, bend.radius_mm, radius)
                except BentTubeError as error:
                    raise FreeArmError(f'Недопустимый изгиб: {error}') from error

    @property
    def anchors(self) -> tuple[Point3, Point3, Point3]:
        return self.front_mm, self.rear_mm, self.outer_mm

    def centerlines(self) -> tuple[tuple[Point3, ...], tuple[Point3, ...]]:
        """Приближение дуг для эскиза, не CAD-геометрия и не готовая деталь."""
        paths = []
        for start, bend in ((self.front_mm, self.front_bend), (self.rear_mm, self.rear_bend)):
            paths.append((start, self.outer_mm) if bend is None else
                         make_bend_path(start, bend.vertex_mm, self.outer_mm, bend.radius_mm, self.radius_mm).sample())
        return paths[0], paths[1]
