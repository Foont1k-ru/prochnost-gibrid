"""Временный плоский эскиз: аналитическая геометрия без связи с проектом."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Literal

Point = tuple[float, float]
Kind = Literal["line", "circle"]
LIMIT_MM = 1_000_000.0
MIN_SIZE_MM = 1e-6
MAX_ENTITIES = 5000


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
    """История команд изолирована от проекта и его отмены."""

    def __init__(self) -> None:
        self.entities: list[Entity] = []
        self._redo: list[Entity] = []

    def add(self, kind: Kind, start: Point, end: Point) -> None:
        if len(self.entities) >= MAX_ENTITIES:
            raise ValueError("Достигнут предел элементов эскиза")
        self.entities.append(make_entity(kind, start, end))
        self._redo.clear()

    def undo(self) -> None:
        if self.entities:
            self._redo.append(self.entities.pop())

    def redo(self) -> None:
        if self._redo:
            self.entities.append(self._redo.pop())
