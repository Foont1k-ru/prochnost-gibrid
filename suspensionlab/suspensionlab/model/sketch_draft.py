"""Изолированная аналитическая геометрия плоского эскиза, координаты в мм."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, isfinite, radians, sin
from typing import Literal

Point = tuple[float, float]
Kind = Literal["line", "circle", "arc"]
LIMIT_MM = 1_000_000.0
MIN_SIZE_MM = 1e-6
MAX_ENTITIES = 5000
MAX_HISTORY = 100


@dataclass(frozen=True)
class Entity:
    kind: Kind
    start: Point
    # Для окружности: вторая точка на окружности, не полигон.
    end: Point
    # Для дуги: угол поворота от радиуса end вокруг start, в градусах.
    sweep_deg: float | None = None

    @property
    def size(self) -> float:
        return hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])


def arc_end(entity: Entity) -> Point:
    if entity.kind != "arc" or entity.sweep_deg is None:
        raise ValueError("Ожидалась дуга")
    a = atan2(entity.end[1] - entity.start[1], entity.end[0] - entity.start[0]) + radians(entity.sweep_deg)
    return entity.start[0] + entity.size * cos(a), entity.start[1] + entity.size * sin(a)


def make_entity(kind: Kind, start: Point, end: Point, sweep_deg: float | None = None) -> Entity:
    if kind not in ("line", "circle", "arc"):
        raise ValueError("Неизвестный инструмент")
    if not all(isfinite(v) and abs(v) <= LIMIT_MM for v in (*start, *end)):
        raise ValueError("Координаты должны быть конечными и не более ±1 000 000 мм")
    if kind == "arc":
        if sweep_deg is None or not isfinite(sweep_deg) or not 1e-6 <= abs(sweep_deg) < 360:
            raise ValueError("Угол дуги должен быть между 0 и 360 градусами, без нуля")
    elif sweep_deg is not None:
        raise ValueError("Угол допустим только для дуги")
    entity = Entity(kind, start, end, sweep_deg)
    if entity.size < MIN_SIZE_MM:
        raise ValueError("Длина или радиус должны быть больше нуля")
    if kind == "arc" and not all(abs(v) <= LIMIT_MM for v in arc_end(entity)):
        raise ValueError("Конечная точка дуги вне допустимых границ")
    return entity


def rectangle_entities(first: Point, opposite: Point) -> tuple[Entity, ...]:
    """Прямоугольник по диагонали; проверка всех сторон до изменения документа."""
    a = first
    b = (opposite[0], first[1])
    c = opposite
    d = (first[0], opposite[1])
    return tuple(make_entity("line", start, end) for start, end in ((a, b), (b, c), (c, d), (d, a)))


def drawing_bounds(entities: tuple[Entity, ...]) -> tuple[float, float, float, float] | None:
    """Габариты в плоскости, включая всю аналитическую окружность."""
    if not entities:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for entity in entities:
        if entity.kind in ("circle", "arc"):
            radius = entity.size
            xs.extend((entity.start[0] - radius, entity.start[0] + radius))
            ys.extend((entity.start[1] - radius, entity.start[1] + radius))
        else:
            xs.extend((entity.start[0], entity.end[0]))
            ys.extend((entity.start[1], entity.end[1]))
    return min(xs), min(ys), max(xs), max(ys)


class SketchDraft:
    """Независимая ограниченная история добавлений, удаления и редактирования."""

    def __init__(self, entities: tuple[Entity, ...] = ()) -> None:
        if len(entities) > MAX_ENTITIES:
            raise ValueError("Достигнут предел элементов эскиза")
        self.entities: list[Entity] = [make_entity(e.kind, e.start, e.end, e.sweep_deg) for e in entities]
        self._undo: list[tuple[Entity, ...]] = []
        self._redo: list[tuple[Entity, ...]] = []

    def _checkpoint(self) -> None:
        self._undo.append(tuple(self.entities))
        if len(self._undo) > MAX_HISTORY:
            del self._undo[0]
        self._redo.clear()

    def add(self, kind: Kind, start: Point, end: Point) -> None:
        if len(self.entities) >= MAX_ENTITIES:
            raise ValueError("Достигнут предел элементов эскиза")
        entity = make_entity(kind, start, end)
        self._checkpoint()
        self.entities.append(entity)

    def add_rectangle(self, first: Point, opposite: Point) -> None:
        if len(self.entities) + 4 > MAX_ENTITIES:
            raise ValueError("Недостаточно места для четырёх сторон прямоугольника")
        parts = rectangle_entities(first, opposite)
        self._checkpoint()
        self.entities.extend(parts)

    def add_arc(self, center: Point, start: Point, sweep_deg: float) -> None:
        if len(self.entities) >= MAX_ENTITIES:
            raise ValueError("Достигнут предел элементов эскиза")
        entity = make_entity("arc", center, start, sweep_deg)
        self._checkpoint()
        self.entities.append(entity)

    def replace(self, index: int, kind: Kind, start: Point, end: Point, sweep_deg: float | None = None) -> None:
        entity = make_entity(kind, start, end, sweep_deg)
        if index < 0 or index >= len(self.entities):
            raise IndexError("Элемент не найден")
        if self.entities[index] != entity:
            self._checkpoint()
            self.entities[index] = entity

    def replace_with(self, index: int, parts: tuple[Entity, ...]) -> None:
        if index < 0 or index >= len(self.entities):
            raise IndexError("Элемент не найден")
        if len(self.entities) - 1 + len(parts) > MAX_ENTITIES:
            raise ValueError("Достигнут предел элементов эскиза")
        validated = [make_entity(e.kind, e.start, e.end, e.sweep_deg) for e in parts]
        self._checkpoint()
        self.entities[index:index + 1] = validated

    def delete(self, index: int) -> None:
        if index < 0 or index >= len(self.entities):
            raise IndexError("Элемент не найден")
        self._checkpoint()
        del self.entities[index]

    def undo(self) -> None:
        if self._undo:
            self._redo.append(tuple(self.entities))
            self.entities = list(self._undo.pop())

    def redo(self) -> None:
        if self._redo:
            self._undo.append(tuple(self.entities))
            self.entities = list(self._redo.pop())
