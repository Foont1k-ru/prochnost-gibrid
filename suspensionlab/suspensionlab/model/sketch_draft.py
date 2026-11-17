"""Изолированная аналитическая геометрия плоского эскиза, координаты в мм."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, copysign, cos, degrees, hypot, isfinite, radians, sin
from typing import Literal

Point = tuple[float, float]
Kind = Literal["line", "circle", "arc"]
LIMIT_MM = 1_000_000.0
MIN_SIZE_MM = 1e-6
MAX_ENTITIES = 5000
MAX_HISTORY = 100
MAX_DIMENSIONS = 1000


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


@dataclass(frozen=True)
class Dimension:
    """Справочный размер, привязанный к элементу по индексу документа."""
    entity_index: int
    position: Point
    mode: str = "auto"


def dimension_value(dimension: Dimension, entity: Entity) -> float:
    mode = dimension.mode
    if mode == "auto":
        mode = "length" if entity.kind == "line" else "radius"
    if mode in ("length", "radius"):
        return entity.size
    if mode == "horizontal":
        return abs(entity.end[0] - entity.start[0])
    if mode == "vertical":
        return abs(entity.end[1] - entity.start[1])
    if mode == "inclination":
        return degrees(atan2(entity.end[1] - entity.start[1], entity.end[0] - entity.start[0]))
    if mode == "diameter":
        return 2 * entity.size
    assert mode == "angle" and entity.sweep_deg is not None
    return abs(entity.sweep_deg)


def dimension_text(dimension: Dimension, entity: Entity) -> str:
    mode = dimension.mode
    value = dimension_value(dimension, entity)
    prefix = "R " if mode == "radius" or (mode == "auto" and entity.kind != "line") else "⌀ " if mode == "diameter" else "∠ " if mode in ("angle", "inclination") else ""
    suffix = "°" if mode in ("angle", "inclination") else " мм"
    return f"{prefix}{value:.3f}{suffix}"


def validate_dimension(dimension: Dimension, entities: tuple[Entity, ...]) -> Dimension:
    index = dimension.entity_index
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(entities):
        raise ValueError("Размер ссылается на отсутствующий элемент")
    if len(dimension.position) != 2 or not all(isfinite(x) and abs(x) <= LIMIT_MM for x in dimension.position):
        raise ValueError("Позиция размера вне допустимых границ")
    allowed = {"auto", "length", "horizontal", "vertical", "inclination"} if entities[index].kind == "line" else {"auto", "radius", "diameter"}
    if entities[index].kind == "arc":
        allowed.add("angle")
    if not isinstance(dimension.mode, str) or dimension.mode not in allowed:
        raise ValueError("Вид размера не подходит для выбранного элемента")
    return dimension


class SketchDraft:
    """Независимая ограниченная история добавлений, удаления и редактирования."""

    def __init__(self, entities: tuple[Entity, ...] = (), dimensions: tuple[Dimension, ...] = ()) -> None:
        if len(entities) > MAX_ENTITIES:
            raise ValueError("Достигнут предел элементов эскиза")
        self.entities: list[Entity] = [make_entity(e.kind, e.start, e.end, e.sweep_deg) for e in entities]
        if len(dimensions) > MAX_DIMENSIONS:
            raise ValueError("Слишком много размеров")
        self.dimensions: list[Dimension] = [validate_dimension(d, tuple(self.entities)) for d in dimensions]
        self._undo: list[tuple[tuple[Entity, ...], tuple[Dimension, ...]]] = []
        self._redo: list[tuple[tuple[Entity, ...], tuple[Dimension, ...]]] = []

    def _state(self) -> tuple[tuple[Entity, ...], tuple[Dimension, ...]]:
        return tuple(self.entities), tuple(self.dimensions)

    def _restore(self, state: tuple[tuple[Entity, ...], tuple[Dimension, ...]]) -> None:
        self.entities, self.dimensions = list(state[0]), list(state[1])

    def _checkpoint(self) -> None:
        self._undo.append(self._state())
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
        if self.entities[index].kind != entity.kind and any(d.entity_index == index for d in self.dimensions):
            raise ValueError("Удалите размер перед изменением типа элемента")
        if self.entities[index] != entity:
            self._checkpoint()
            self.entities[index] = entity

    def replace_with(self, index: int, parts: tuple[Entity, ...]) -> None:
        if index < 0 or index >= len(self.entities):
            raise IndexError("Элемент не найден")
        if len(self.entities) - 1 + len(parts) > MAX_ENTITIES:
            raise ValueError("Достигнут предел элементов эскиза")
        if any(d.entity_index == index for d in self.dimensions):
            raise ValueError("Удалите размер этого элемента перед обрезкой")
        validated = [make_entity(e.kind, e.start, e.end, e.sweep_deg) for e in parts]
        self._checkpoint()
        self.entities[index:index + 1] = validated
        delta = len(validated) - 1
        self.dimensions = [Dimension(d.entity_index + delta if d.entity_index > index else d.entity_index, d.position, d.mode)
                           for d in self.dimensions]

    def delete(self, index: int) -> None:
        if index < 0 or index >= len(self.entities):
            raise IndexError("Элемент не найден")
        if any(d.entity_index == index for d in self.dimensions):
            raise ValueError("Удалите размер этого элемента перед удалением")
        self._checkpoint()
        del self.entities[index]
        self.dimensions = [Dimension(d.entity_index - 1 if d.entity_index > index else d.entity_index, d.position, d.mode)
                           for d in self.dimensions]

    def add_dimension(self, index: int, position: Point, mode: str = "auto") -> None:
        if len(self.dimensions) >= MAX_DIMENSIONS:
            raise ValueError("Достигнут предел количества размеров")
        dim = validate_dimension(Dimension(index, position, mode), tuple(self.entities))
        self._checkpoint()
        self.dimensions.append(dim)

    def set_dimension_value(self, index: int, value: float) -> None:
        """Одноразово изменить только указанный элемент; постоянной связи нет."""
        if not 0 <= index < len(self.dimensions):
            raise IndexError("Размер не найден")
        if not isfinite(value):
            raise ValueError("Введите конечное число")
        dim = self.dimensions[index]
        entity = self.entities[dim.entity_index]
        mode = dim.mode if dim.mode != "auto" else ("length" if entity.kind == "line" else "radius")
        dx, dy = entity.end[0] - entity.start[0], entity.end[1] - entity.start[1]
        if mode == "inclination":
            if not -180 <= value <= 180:
                raise ValueError("Угол наклона должен быть от −180 до 180 градусов")
            x, y = entity.size * cos(radians(value)), entity.size * sin(radians(value))
        elif mode == "angle":
            if not 1e-6 <= value < 360:
                raise ValueError("Угол дуги должен быть больше нуля и меньше 360 градусов")
            assert entity.sweep_deg is not None
            self.replace(dim.entity_index, "arc", entity.start, entity.end, copysign(value, entity.sweep_deg))
            return
        else:
            if value < 0 or (value < MIN_SIZE_MM and mode not in ("horizontal", "vertical")):
                raise ValueError("Значение должно быть положительным")
            if mode == "horizontal":
                x, y = copysign(value, dx), dy
            elif mode == "vertical":
                x, y = dx, copysign(value, dy)
            else:
                radius = value / 2 if mode == "diameter" else value
                x, y = dx * radius / entity.size, dy * radius / entity.size
        self.replace(dim.entity_index, entity.kind, entity.start,
                     (entity.start[0] + x, entity.start[1] + y), entity.sweep_deg)

    def delete_dimension(self, index: int) -> None:
        if index < 0 or index >= len(self.dimensions):
            raise IndexError("Размер не найден")
        self._checkpoint()
        del self.dimensions[index]

    def apply_fillet(self, first: int, second: int, pieces: tuple[Entity, Entity, Entity]) -> None:
        if first == second or min(first, second) < 0 or max(first, second) >= len(self.entities):
            raise ValueError("Выберите два разных отрезка")
        if self.entities[first].kind != "line" or self.entities[second].kind != "line":
            raise ValueError("Для скругления выберите два отрезка")
        if len(self.entities) >= MAX_ENTITIES:
            raise ValueError("Достигнут предел элементов эскиза")
        validated = tuple(make_entity(e.kind, e.start, e.end, e.sweep_deg) for e in pieces)
        if tuple(e.kind for e in validated) != ("line", "line", "arc"):
            raise ValueError("Некорректное сопряжение")
        self._checkpoint()
        self.entities[first], self.entities[second] = validated[0], validated[1]
        self.entities.append(validated[2])

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self._state())
            self._restore(self._undo.pop())

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self._state())
            self._restore(self._redo.pop())
