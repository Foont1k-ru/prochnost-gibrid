"""Контроллер приложения: единственное место, где меняется модель.

Виджеты не правят данные напрямую: они вызывают методы контроллера,
которые выполняют команды через стек отмены и рассылают сигналы. Это
разделение «модель ↔ представление» из ТЗ (§9) и гарантия того, что
любое изменение попадает в историю.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..config import autosave_path
from ..model.commands import (
    ChangeLinkLengthCommand,
    DictFlagCommand,
    PointMoveCommand,
    SetAxleTypeCommand,
    UndoStack,
    ValueCommand,
)
from ..model.entities import Axle, Hardpoint, Project, Snapshot
from ..model.project_io import ProjectIOError, load_project, save_project
from ..model.templates import load_template
from ..model.units import UnitSettings
from ..model.validation import Issue, validate_project

LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Selection:
    """Выбранный элемент дерева проекта или схемы."""

    kind: str  # project | vehicle | axle | point | link | wheel | spring | ...
    role: str = ""
    code: str = ""


class AppController(QObject):
    """Состояние приложения и команды редактирования."""

    projectReplaced = Signal()
    modelChanged = Signal()
    selectionChanged = Signal(object)
    statusMessage = Signal(str)
    dirtyChanged = Signal(bool)
    unitsChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project: Project = Project.create_default()
        self.project.path = None
        self.undo = UndoStack()
        self.units = UnitSettings()
        self.selection: Selection | None = None
        self.dirty = False
        self.auto_extend_slider = True
        self._issues: list[Issue] = []
        self.undo.add_listener(self._on_undo_changed)
        self._revalidate()

    # ------------------------------------------------------------------ файлы
    def new_project(self, template_key: str | None = None, project: Project | None = None) -> None:
        """Создаёт новый проект (пустой или из шаблона)."""
        if project is not None:
            self.project = project
        elif template_key:
            self.project = load_template(template_key)
            LOG.info("Создан проект из шаблона %s", template_key)
        else:
            self.project = Project.create_default()
            self.project.meta.name = ""
            LOG.info("Создан пустой проект")
        self.project.path = None
        self.undo.clear()
        self.selection = None
        self._set_dirty(False)
        self._revalidate()
        self.projectReplaced.emit()
        self.selectionChanged.emit(None)
        self.statusMessage.emit("status.ready")

    def open_project(self, path: str | Path) -> None:
        """Открывает проект из файла; ошибки — в виде исключения ProjectIOError."""
        project = load_project(path)
        self.project = project
        self.undo.clear()
        self.selection = None
        self._set_dirty(False)
        self._revalidate()
        self.projectReplaced.emit()
        self.selectionChanged.emit(None)
        self.statusMessage.emit("status.saved")

    def save_project(self, path: str | Path | None = None) -> Path:
        """Сохраняет проект; возвращает путь файла."""
        target = path or self.project.path
        if not target:
            raise ProjectIOError("error.project.write_failed", path="")
        saved_path = save_project(self.project, target)
        self._set_dirty(False)
        self.statusMessage.emit("status.saved")
        return saved_path

    def autosave(self) -> bool:
        """Тихое автосохранение рабочей копии (раз в минуту)."""
        original_path = self.project.path
        try:
            save_project(self.project, autosave_path())
        except ProjectIOError:
            LOG.warning("Автосохранение не удалось", exc_info=True)
            self.statusMessage.emit("autosave.failed")
            return False
        finally:
            self.project.path = original_path
        self.statusMessage.emit("autosave.done")
        return True

    # ------------------------------------------------------------------ выбор
    def select(self, selection: Selection | None) -> None:
        """Меняет текущий выбранный элемент."""
        if selection == self.selection:
            return
        self.selection = selection
        self.selectionChanged.emit(selection)

    # ------------------------------------------------------------------ единицы
    def set_units(self, units: UnitSettings) -> None:
        """Применяет настройки единиц отображения."""
        self.units = units
        self.unitsChanged.emit()
        self.modelChanged.emit()

    # ------------------------------------------------------------------ правка
    def set_value(
        self,
        owner: object,
        attr: str,
        value: object,
        label_key: str = "undo.value",
        merge_key: str | None = None,
    ) -> None:
        """Устанавливает атрибут объекта модели через команду."""
        old = getattr(owner, attr)
        if old == value:
            return
        command = ValueCommand(owner, attr, old, value, label_key, merge_key or f"{id(owner)}:{attr}")
        self.undo.push(command)
        self._touch()

    def move_point(self, point: Hardpoint, xyz: tuple[float, float, float]) -> None:
        """Перемещает точку крепления (перетаскивание или поле ввода)."""
        if (point.x, point.y, point.z) == xyz:
            return
        self.undo.push(PointMoveCommand(point, (point.x, point.y, point.z), xyz))
        self._touch()

    def set_link_length(self, axle: Axle, code: str, length: float) -> None:
        """Меняет длину рычага числом, смещая выбранный конец (Р-3)."""
        self.undo.push(ChangeLinkLengthCommand(axle, code, length))
        self._touch()

    def set_axle_type(self, role: str, type_code: str) -> None:
        """Меняет тип подвески оси."""
        axle = self.project.axle(role)
        if axle.type_code == type_code:
            return
        self.undo.push(SetAxleTypeCommand(axle, type_code))
        self.projectReplaced.emit()
        self._touch()

    def add_snapshot(self, name: str) -> None:
        """Добавляет именованный снимок как отдельную отменяемую команду."""
        name = name.strip()
        if not name:
            return
        old = list(self.project.snapshots)
        snapshot = Snapshot(name=name, data=self.project._to_dict_without_b())
        self.undo.push(ValueCommand(self.project, "snapshots", old, [*old, snapshot], "undo.snapshot"))
        self._touch()

    def set_lock(self, key: str, locked: bool) -> None:
        """Фиксирует или расфиксирует параметр (замок в модели проекта)."""
        self.undo.push(DictFlagCommand(self.project.locks, key, locked))
        self._touch()

    def is_locked(self, key: str) -> bool:
        """Зафиксирован ли параметр."""
        return bool(self.project.locks.get(key, False))

    def undo_last(self) -> None:
        """Отменяет последнее изменение."""
        if self.undo.undo():
            self.projectReplaced.emit()
            self._touch(validate=True)

    def redo_last(self) -> None:
        """Повторяет отменённое изменение."""
        if self.undo.redo():
            self.projectReplaced.emit()
            self._touch(validate=True)

    # ------------------------------------------------------------------ диагностика
    @property
    def issues(self) -> list[Issue]:
        """Текущий список сообщений проверки модели."""
        return self._issues

    def _revalidate(self) -> None:
        """Пересчитывает сообщения проверки модели."""
        self._issues = validate_project(self.project)

    def _touch(self, validate: bool = True) -> None:
        """Уведомляет интерфейс об изменении модели."""
        if validate:
            self._revalidate()
        self._set_dirty(True)
        self.modelChanged.emit()

    def _set_dirty(self, dirty: bool) -> None:
        """Меняет признак «есть несохранённые изменения»."""
        if self.dirty != dirty:
            self.dirty = dirty
            self.dirtyChanged.emit(dirty)

    def _on_undo_changed(self) -> None:
        """Обновляет состояние действий «Отменить/Повторить»."""
        self.modelChanged.emit()
