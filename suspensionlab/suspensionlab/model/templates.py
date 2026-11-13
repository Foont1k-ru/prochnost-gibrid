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


@dataclass(frozen=True, slots=True)
class VehicleTemplateOptions:
    """Конфигурация учебного шаблона; редуктор задаётся только точками."""

    category: str = "passenger"
    front_type: str = "macpherson_front"
    rear_type: str = "multilink_rear"
    front_driven: bool = True
    rear_driven: bool = False


def create_vehicle_template(options: VehicleTemplateOptions) -> Project:
    """Создаёт отдельные оси без подмены типа подвески или расчётной модели."""
    from .entities import Axle

    allowed = {
        "passenger": (("macpherson_front", "multilink_front", "double_wishbone"),
                      ("multilink_rear", "torsion_beam_rear")),
        "suv": (("multilink_front", "double_wishbone"), ("multilink_rear", "live_axle_coil")),
    }
    if options.category not in allowed:
        raise ValueError("Unknown vehicle category")
    front_types, rear_types = allowed[options.category]
    if options.front_type not in front_types or options.rear_type not in rear_types:
        raise ValueError("Unsupported suspension for vehicle category")
    if options.rear_type == "torsion_beam_rear" and options.rear_driven:
        raise ValueError("Driven torsion beam is not represented")
    front = Axle(role="front", type_code=options.front_type)
    rear = Axle(role="rear", type_code=options.rear_type)
    front.layout = front.spec.default_layout
    rear.layout = rear.spec.default_layout
    front.drivetrain.driven = options.front_driven
    rear.drivetrain.driven = options.rear_driven
    project = Project(front=front, rear=rear)
    project.meta.name = ""
    return project
