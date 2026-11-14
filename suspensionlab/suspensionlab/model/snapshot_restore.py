"""Подготовка и отменяемое восстановление выбранной части снимка."""
from __future__ import annotations

import copy
import json
from typing import Any

from .commands import Command
from .entities import SCHEMA_VERSION, Project

_FIELDS = ("meta", "vehicle", "front_axle", "rear_axle")


def prepare_snapshot(data: dict[str, Any]) -> Project:
    """Принимает только снимок текущей схемы без незаметной подстановки данных.

    Проверка не является инженерной валидацией. Восстанавливаются только
    метаданные, автомобиль и две оси; остальные поля текущего проекта не меняются.
    """
    if data.get("schema_version") != SCHEMA_VERSION or any(not isinstance(data.get(k), dict) for k in _FIELDS):
        raise ValueError("Неполный или неподдерживаемый снимок")
    try:
        selected = {key: copy.deepcopy(data[key]) for key in _FIELDS}
        json.dumps(selected, allow_nan=False)
        restored = Project.from_dict(selected)
        normalized = restored.to_dict()
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise ValueError("Повреждённые данные снимка") from error
    if any(selected[key] != normalized[key] for key in _FIELDS):
        raise ValueError("Снимок неполон или несовместим с текущей схемой")
    return restored


class RestoreSnapshotCommand(Command):
    """Меняет выбранные объекты, сохраняя ссылки для прежней истории отмены."""

    label_key = "undo.restore_snapshot"

    def __init__(self, project: Project, restored: Project) -> None:
        super().__init__()
        self.project = project
        self.old = (project.meta, project.vehicle, project.front, project.rear)
        self.new = (restored.meta, restored.vehicle, restored.front, restored.rear)

    def redo(self) -> None:
        self.project.meta, self.project.vehicle, self.project.front, self.project.rear = self.new

    def undo(self) -> None:
        self.project.meta, self.project.vehicle, self.project.front, self.project.rear = self.old
