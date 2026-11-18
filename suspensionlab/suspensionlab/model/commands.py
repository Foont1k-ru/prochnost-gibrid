"""Команды редактирования и стек отмены/повтора.

Стек неограниченный (требование ТЗ, §6.8). Команды не зависят от Qt:
интерфейс подписывается на изменения через слушателей и обновляет
действия «Отменить/Повторить».

Перетаскивание ползунка порождает поток команд; они объединяются по
``merge_key`` в пределах короткого окна времени, поэтому один жест даёт
одну запись в истории, а не двести.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Sequence
from typing import Any

from .entities import Axle, Hardpoint, Project
from .suspension_types import REGISTRY

#: Окно объединения последовательных правок, секунды.
MERGE_WINDOW_S = 1.5


class Command:
    """Базовая команда: умеет выполняться, откатываться и объединяться."""

    #: Ключ локализации подписи действия для меню «Правка».
    label_key: str = "undo.generic"

    def __init__(self, merge_key: str | None = None) -> None:
        self.merge_key = merge_key

    def redo(self) -> None:
        """Применяет изменение."""
        raise NotImplementedError

    def undo(self) -> None:
        """Отменяет изменение."""
        raise NotImplementedError

    def merge(self, other: Command) -> bool:
        """Поглощает следующую команду; True — объединение выполнено."""
        return False


class ValueCommand(Command):
    """Изменение числового/строкового/логического атрибута объекта модели."""

    def __init__(
        self,
        owner: Any,
        attr: str,
        old: Any,
        new: Any,
        label_key: str = "undo.value",
        merge_key: str | None = None,
    ) -> None:
        super().__init__(merge_key)
        self.owner = owner
        self.attr = attr
        self.old = old
        self.new = new
        self.label_key = label_key

    def redo(self) -> None:
        """Устанавливает новое значение."""
        setattr(self.owner, self.attr, self.new)

    def undo(self) -> None:
        """Возвращает прежнее значение."""
        setattr(self.owner, self.attr, self.old)

    def merge(self, other: Command) -> bool:
        """Объединяет правки одного и того же атрибута."""
        if (
            isinstance(other, ValueCommand)
            and other.owner is self.owner
            and other.attr == self.attr
            and other.merge_key == self.merge_key
        ):
            self.new = other.new
            return True
        return False


class PointMoveCommand(Command):
    """Перемещение точки крепления по одной или нескольким осям."""

    def __init__(
        self,
        point: Hardpoint,
        old: tuple[float, float, float],
        new: tuple[float, float, float],
        label_key: str = "undo.point_move",
    ) -> None:
        super().__init__(f"point:{id(point)}")
        self.point = point
        self.old = old
        self.new = new
        self.label_key = label_key

    def redo(self) -> None:
        """Применяет новые координаты."""
        self.point.x, self.point.y, self.point.z = self.new

    def undo(self) -> None:
        """Возвращает прежние координаты."""
        self.point.x, self.point.y, self.point.z = self.old

    def merge(self, other: Command) -> bool:
        """Объединяет последовательные перемещения одной точки."""
        if isinstance(other, PointMoveCommand) and other.point is self.point:
            self.new = other.new
            return True
        return False


class MultiCommand(Command):
    """Группа команд, выполняемая как одна операция (например, drag рычага)."""

    def __init__(self, commands: Sequence[Command], label_key: str = "undo.multi") -> None:
        super().__init__(None)
        self.commands = list(commands)
        self.label_key = label_key

    def redo(self) -> None:
        """Выполняет все команды по порядку."""
        for command in self.commands:
            command.redo()

    def undo(self) -> None:
        """Отменяет команды в обратном порядке."""
        for command in reversed(self.commands):
            command.undo()


class ChangeLinkLengthCommand(Command):
    """Изменение длины рычага числом (Р-3) со смещением выбранного конца."""

    def __init__(self, axle: Axle, link_code: str, new_length: float, label_key: str = "undo.link_length") -> None:
        super().__init__(f"link:{id(axle)}:{link_code}")
        self.axle = axle
        self.link_code = link_code
        self.new_length = max(1.0, float(new_length))
        self.label_key = label_key
        self._old_points: dict[str, tuple[float, float, float]] = {}
        self._new_points: dict[str, tuple[float, float, float]] = {}
        self._prepare()

    # ------------------------------------------------------------------ расчёт
    def _prepare(self) -> None:
        """Вычисляет новые координаты точек по режиму редактирования."""
        spec = self.axle.link_spec(self.link_code)
        if spec is None:
            self.new_length = 0.0
            return
        points = self.axle.hardpoints
        if spec.end not in points:
            return
        for code in (*spec.pivot, spec.end):
            if code in points:
                self._old_points[code] = points[code].as_tuple()
        mode = self.axle.links[self.link_code].edit_mode if self.link_code in self.axle.links else "move_outer"

        from ..core.geometry import (
            axis_length,
            distance,
            midpoint,
            v_add,
            v_normalize,
            v_scale,
            v_sub,
        )

        end = points[spec.end]
        if len(spec.pivot) >= 2:
            p1 = points[spec.pivot[0]].as_tuple()
            p2 = points[spec.pivot[1]].as_tuple()
            direction = v_sub(end.as_tuple(), midpoint(p1, p2))
        else:
            p1 = points[spec.pivot[0]].as_tuple()
            direction = v_sub(end.as_tuple(), p1)
        current = axis_length([points[c].as_tuple() for c in (*spec.pivot, spec.end) if c in points])
        if current <= 1e-6:
            return
        unit = v_normalize(direction)
        if unit == (0.0, 0.0, 0.0):
            return

        if mode == "move_outer":
            base = midpoint(p1, p2) if len(spec.pivot) >= 2 else p1
            new_end = v_add(base, v_scale(unit, self.new_length))
            self._new_points[spec.end] = new_end
        elif mode == "move_inner" and len(spec.pivot) >= 2:
            # внутренние точки смещаются так, чтобы ось качания осталась
            # параллельной самой себе, а длина стала заданной
            shift = self.new_length - current
            for code in spec.pivot:
                p = points[code].as_tuple()
                self._new_points[code] = v_add(p, v_scale(unit, -shift))
        else:  # move_both — делим поправку поровну между концами рычага
            delta = (self.new_length - current) / 2.0
            self._new_points[spec.end] = v_add(points[spec.end].as_tuple(), v_scale(unit, delta))
            if len(spec.pivot) >= 2:
                for code in spec.pivot:
                    self._new_points[code] = v_add(points[code].as_tuple(), v_scale(unit, -delta))
        # сохраняем режим «только по оси рычага»: точки не смещаются поперёк
        for code, xyz in list(self._new_points.items()):
            if distance(xyz, points[code].as_tuple()) < 1e-9:
                self._new_points.pop(code)

    # ------------------------------------------------------------------ выполнение
    def redo(self) -> None:
        """Применяет новые координаты точек."""
        for code, xyz in self._new_points.items():
            point = self.axle.hardpoints[code]
            point.x, point.y, point.z = xyz

    def undo(self) -> None:
        """Возвращает координаты точек к исходным."""
        for code, xyz in self._old_points.items():
            point = self.axle.hardpoints[code]
            point.x, point.y, point.z = xyz

    def merge(self, other: Command) -> bool:
        """Объединяет повторные правки длины того же рычага."""
        if isinstance(other, ChangeLinkLengthCommand) and other.link_code == self.link_code and other.axle is self.axle:
            self.new_length = other.new_length
            self._new_points = other._new_points
            return True
        return False


class SetAxleTypeCommand(Command):
    """Смена типа подвески оси с возможностью отмены."""

    def __init__(self, axle: Axle, new_type: str) -> None:
        super().__init__(None)
        self.axle = axle
        self.new_type = new_type
        self.old_type = axle.type_code
        self.old_layout = axle.layout
        # Сохраняем сами объекты: более ранние команды ссылаются на них.
        self.old_points = dict(axle.hardpoints)
        self.old_links = dict(axle.links)
        self.new_points: dict[str, Hardpoint] | None = None
        self.new_links: dict[str, Any] | None = None
        self.label_key = "undo.axle_type"

    def redo(self) -> None:
        """Устанавливает новый тип и добавляет недостающие точки."""
        self.axle.type_code = self.new_type
        self.axle.layout = REGISTRY[self.new_type].default_layout
        if self.new_points is None:
            self.axle.ensure_points()
            self.new_points = dict(self.axle.hardpoints)
            self.new_links = dict(self.axle.links)
        else:
            self.axle.hardpoints = dict(self.new_points)
            self.axle.links = dict(self.new_links or {})

    def undo(self) -> None:
        """Возвращает прежний тип и объекты без потери замков и истории."""
        self.axle.type_code = self.old_type
        self.axle.layout = self.old_layout
        self.axle.hardpoints = dict(self.old_points)
        self.axle.links = dict(self.old_links)


class ReplaceProjectCommand(Command):
    """Замена состояния проекта целиком (снимки, оптимизатор, «применить совет»)."""

    def __init__(self, project: Project, new_state: dict[str, Any], label_key: str = "undo.replace") -> None:
        super().__init__(None)
        self.project = project
        self.old_state = copy.deepcopy(project._to_dict_without_b())
        self.new_state = copy.deepcopy(new_state)
        self.label_key = label_key

    def _apply(self, state: dict[str, Any]) -> None:
        """Применяет состояние к проекту «на месте» (ссылки сохраняются)."""
        from .entities import Project as _Project

        restored = _Project.from_dict(copy.deepcopy(state))
        self.project.meta = restored.meta
        self.project.vehicle = restored.vehicle
        self.project.front = restored.front
        self.project.rear = restored.rear

    def redo(self) -> None:
        """Применяет новое состояние."""
        self._apply(self.new_state)

    def undo(self) -> None:
        """Возвращает прежнее состояние."""
        self._apply(self.old_state)


class DictFlagCommand(Command):
    """Изменение флага в словаре (замки параметров, флаги вида)."""

    def __init__(self, container: dict[str, bool], key: str, new_value: bool, label_key: str = "undo.value") -> None:
        super().__init__(f"flag:{id(container)}:{key}")
        self.container = container
        self.key = key
        self.old_value = bool(container.get(key, False))
        self.new_value = bool(new_value)
        self.label_key = label_key

    def redo(self) -> None:
        """Устанавливает флаг."""
        if self.new_value:
            self.container[self.key] = True
        else:
            self.container.pop(self.key, None)

    def undo(self) -> None:
        """Возвращает прежнее состояние флага."""
        if self.old_value:
            self.container[self.key] = True
        else:
            self.container.pop(self.key, None)


class UndoStack:
    """Стек команд с объединением и уведомлением слушателей."""

    def __init__(self, merge_window_s: float = MERGE_WINDOW_S) -> None:
        self._commands: list[Command] = []
        self._index = 0
        self._listeners: list[Callable[[], None]] = []
        self._merge_window_s = merge_window_s
        self._last_push_time = 0.0

    # ------------------------------------------------------------------ состояние
    @property
    def can_undo(self) -> bool:
        """Есть ли что отменять."""
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        """Есть ли что повторять."""
        return self._index < len(self._commands)

    def undo_label_key(self) -> str:
        """Ключ подписи команды, которая будет отменена."""
        return self._commands[self._index - 1].label_key if self.can_undo else "undo.none"

    def redo_label_key(self) -> str:
        """Ключ подписи команды, которая будет повторена."""
        return self._commands[self._index].label_key if self.can_redo else "undo.none"

    def depth(self) -> int:
        """Текущее количество доступных для отмены шагов."""
        return self._index

    def clear(self) -> None:
        """Очищает историю (например, при открытии другого проекта)."""
        self._commands.clear()
        self._index = 0
        self._notify()

    # ------------------------------------------------------------------ действия
    def push(self, command: Command) -> None:
        """Выполняет команду и кладёт её в историю (с объединением)."""
        now = time.monotonic()
        # всё, что было «впереди» после отмен, отбрасывается
        if self._index < len(self._commands):
            del self._commands[self._index :]
        command.redo()
        top = self._commands[-1] if self._commands else None
        if (
            top is not None
            and command.merge_key is not None
            and command.merge_key == top.merge_key
            and now - self._last_push_time <= self._merge_window_s
            and top.merge(command)
        ):
            self._last_push_time = now
            self._notify()
            return
        self._commands.append(command)
        self._index = len(self._commands)
        self._last_push_time = now
        self._notify()

    def undo(self) -> bool:
        """Отменяет последнюю команду."""
        if not self.can_undo:
            return False
        self._index -= 1
        self._commands[self._index].undo()
        self._last_push_time = 0.0
        self._notify()
        return True

    def redo(self) -> bool:
        """Повторяет отменённую команду."""
        if not self.can_redo:
            return False
        self._commands[self._index].redo()
        self._index += 1
        self._last_push_time = 0.0
        self._notify()
        return True

    def jump_to(self, depth: int) -> None:
        """Возвращает состояние к шагу ``depth`` (0 — самое начало)."""
        depth = max(0, min(depth, len(self._commands)))
        while self._index > depth:
            self.undo()
        while self._index < depth:
            self.redo()

    # ------------------------------------------------------------------ слушатели
    def add_listener(self, callback: Callable[[], None]) -> None:
        """Подписка на любые изменения стека."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        """Отписка."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self) -> None:
        """Оповещает слушателей об изменении состояния."""
        for callback in list(self._listeners):
            callback()
