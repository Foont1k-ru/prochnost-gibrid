"""Шаблоны проектов из комплекта поставки.

Шаблоны — обычные файлы ``.susp.json`` в ``resources/templates`` плюс
``index.json`` с ключами локализации названий и описаний. Это данные,
а не код: пользователь может добавить свой шаблон, положив файл рядом.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import resources_dir
from .entities import Project
from .project_io import ProjectIOError, load_project

LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    """Описание шаблона для окна «Создать из шаблона»."""

    key: str
    file: Path
    title_key: str
    description_key: str


def templates_dir() -> Path:
    """Каталог шаблонов."""
    return resources_dir() / "templates"


def list_templates() -> list[TemplateInfo]:
    """Список доступных шаблонов в порядке индекса."""
    index_path = templates_dir() / "index.json"
    if not index_path.is_file():
        LOG.warning("Индекс шаблонов не найден: %s", index_path)
        return []
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOG.exception("Не удалось прочитать индекс шаблонов")
        return []
    result: list[TemplateInfo] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file", ""))
        path = templates_dir() / file_name
        if not path.is_file():
            continue
        result.append(
            TemplateInfo(
                key=str(item.get("key", file_name)),
                file=path,
                title_key=str(item.get("title_key", "template.unknown.name")),
                description_key=str(item.get("description_key", "template.unknown.desc")),
            )
        )
    return result


def load_template(key: str) -> Project:
    """Загружает проект из шаблона по ключу."""
    for info in list_templates():
        if info.key == key:
            project = load_project(info.file)
            project.path = None
            project.meta.name = ""
            return project
    raise ProjectIOError("error.project.read_failed", path=key)
