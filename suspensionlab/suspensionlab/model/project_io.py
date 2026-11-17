"""Сохранение, загрузка и миграция файлов проекта (``.susp.json``).

Формат — человекочитаемый JSON с полем ``schema_version``. При загрузке
старых файлов выполняется цепочка миграций; при ошибке пользователь
получает сообщение по схеме «что случилось → почему → что сделать»,
а не трассировку стека (подробности остаются в журнале).
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from .. import PROJECT_SUFFIX
from .entities import SCHEMA_VERSION, Project

LOG = logging.getLogger(__name__)


class ProjectIOError(Exception):
    """Ошибка чтения/записи проекта с ключом локализации и параметрами."""

    def __init__(self, message_key: str, **params: object) -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.params = params


# ---------------------------------------------------------------------------
# Миграции схемы
# ---------------------------------------------------------------------------


def _migrate_0_9_to_1_0(data: dict[str, Any]) -> dict[str, Any]:
    """Миграция раннего формата (0.9) к версии 1.0.

    Отличия 0.9:
    * оси лежали в ключах ``front``/``rear``;
    * точки записывались списками ``[x, y, z]``;
    * не было секций ``links`` и ``view``.
    """
    migrated = dict(data)
    for old_key, new_key in (("front", "front_axle"), ("rear", "rear_axle")):
        if old_key in migrated and new_key not in migrated:
            migrated[new_key] = migrated.pop(old_key)
    for key in ("front_axle", "rear_axle"):
        axle = migrated.get(key)
        if not isinstance(axle, dict):
            continue
        points = axle.get("hardpoints")
        if isinstance(points, dict):
            converted: dict[str, Any] = {}
            for code, value in points.items():
                if isinstance(value, (list, tuple)) and len(value) == 3:
                    converted[code] = {"x": value[0], "y": value[1], "z": value[2]}
                else:
                    converted[code] = value
            axle["hardpoints"] = converted
        axle.pop("lengths", None)
        axle.setdefault("links", {})
    migrated.pop("units", None)
    migrated["schema_version"] = "1.0"
    LOG.info("Проект мигрирован из схемы 0.9 в 1.0")
    return migrated


#: Цепочка миграций: версия файла -> функция преобразования.
MIGRATIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "0.9": _migrate_0_9_to_1_0,
}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Приводит словарь проекта к актуальной версии схемы."""
    version = str(data.get("schema_version", "0.9"))
    data = dict(data)
    guard = 0
    while version != SCHEMA_VERSION:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ProjectIOError("error.project.too_new", version=version)
        data = migration(data)
        version = str(data.get("schema_version", SCHEMA_VERSION))
        guard += 1
        if guard > 20:
            raise ProjectIOError("error.project.migration_loop")
    return data


# ---------------------------------------------------------------------------
# Запись и чтение
# ---------------------------------------------------------------------------


def ensure_suffix(path: Path) -> Path:
    """Добавляет расширение ``.susp.json``, если пользователь его не указал."""
    name = path.name
    if name.endswith(PROJECT_SUFFIX):
        return path
    if name.endswith(".json"):
        return path.with_name(name[: -len(".json")] + PROJECT_SUFFIX)
    return path.with_name(name + PROJECT_SUFFIX)


def project_to_json(project: Project) -> str:
    """Сериализует проект в строку JSON (UTF-8, с отступами)."""
    return json.dumps(project.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Повторяющийся ключ неоднозначен, даже внутри сохранённого снимка."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def save_project(project: Project, path: str | Path) -> Path:
    """Сначала записывает временный файл рядом с целью, затем заменяет цель.

    При ошибке прежний файл и путь проекта не изменяются. Символическая
    ссылка на существующий файл остаётся ссылкой: заменяется её цель.
    Атомарная замена не гарантирует сохранность при потере питания.
    """
    target = ensure_suffix(Path(path))
    temporary: str | None = None
    try:
        try:
            text = project_to_json(project)
        except ValueError as error:
            raise ProjectIOError("error.project.invalid_save", path=str(target)) from error
        target.parent.mkdir(parents=True, exist_ok=True)
        destination = target.resolve()
        mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else None
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=destination.parent,
                                         prefix=".suspensionlab-project-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None and os.name != "nt":
            os.chmod(temporary, mode)
        os.replace(temporary, destination)
        temporary = None
    except (OSError, UnicodeError, TypeError, ValueError, OverflowError, RuntimeError) as error:
        LOG.error("Не удалось записать проект %s: %s", target, error)
        raise ProjectIOError("error.project.write_failed", path=str(target)) from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
    project.path = str(target)
    LOG.info("Проект сохранён: %s", target)
    return target


def load_project(path: str | Path, *, require_complete: bool = False) -> Project:
    """Загружает проект; для автосохранения можно запретить неявные значения."""
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        LOG.error("Не удалось прочитать проект %s: %s", source, error)
        raise ProjectIOError("error.project.read_failed", path=str(source)) from error
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        # Reject NaN, Infinity and float overflow (e.g. 1e999), including
        # inside unknown fields and snapshots, before migration or defaults.
        json.dumps(data, allow_nan=False)
    except json.JSONDecodeError as error:
        LOG.error("Повреждённый JSON в %s: %s", source, error)
        raise ProjectIOError("error.project.broken_json", path=str(source), line=error.lineno) from error
    except (ValueError, RecursionError) as error:
        LOG.warning("Недопустимое содержимое JSON проекта %s: %s", source, type(error).__name__)
        raise ProjectIOError("error.project.invalid_json_values", path=str(source)) from error
    if not isinstance(data, dict):
        raise ProjectIOError("error.project.bad_structure", path=str(source))
    if require_complete and data.get("schema_version") != SCHEMA_VERSION:
        raise ProjectIOError("error.project.bad_structure", path=str(source))
    migrated = migrate(data)
    try:
        project = Project.from_dict(migrated)
        # Legacy files accept numeric strings; conversions such as "NaN" or
        # "1e999" must not introduce non-finite values into the live model.
        serialized = project.to_dict()
        json.dumps(serialized, allow_nan=False)
        # from_dict normally fills missing fields with defaults; do not accept
        # partially restored autosaves as complete projects.
        if require_complete and serialized != data:
            raise ValueError("Неполное или несовместимое автосохранение")
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        LOG.error("Несовместимая структура проекта %s: %s", source, error)
        raise ProjectIOError("error.project.bad_structure", path=str(source)) from error
    project.path = str(source)
    LOG.info("Проект загружен: %s", source)
    return project
