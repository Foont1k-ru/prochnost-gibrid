"""Изолированная аналитическая геометрия плоского эскиза, координаты в мм."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Literal

Point = tuple[float, float]
Kind = Literal["line", "circle"]
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

    @property
    def size(self) -> float:
        return hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])


def make_entity(kind: Kind, start: Point, end: Point) -> Entity:
    if kind not in ("line", "circle"):
        raise ValueError("Неизвестный инструмент")
    if not all(isfinite(v) and abs(v) <= LIMIT_MM for v in (*start, *end)):
        raise ValueError("Координаты должны быть конечными и не более ±1 000 000 мм")
    entity = Entity(kind, start, end)
    if entity.size < MIN_SIZE_MM:
        raise ValueError("Длина или радиус должны быть больше нуля")
    return entity


class SketchDraft:
    """Независимая ограниченная история добавлений, удаления и редактирования."""

    def __init__(self, entities: tuple[Entity, ...] = ()) -> None:
        if len(entities) > MAX_ENTITIES:
            raise ValueError("Достигнут предел элементов эскиза")
        self.entities: list[Entity] = [make_entity(e.kind, e.start, e.end) for e in entities]
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

    def replace(self, index: int, kind: Kind, start: Point, end: Point) -> None:
        entity = make_entity(kind, start, end)
        if index < 0 or index >= len(self.entities):
            raise IndexError("Элемент не найден")
        if self.entities[index] != entity:
            self._checkpoint()
            self.entities[index] = entity

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
