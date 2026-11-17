"""Исследовательские файлы KIM: точный контракт прототипа, не готовый CAD.

Версия 0.1 умеет лишь тестовый цилиндр и экземпляры с переносом. Сборка
содержит детали внутри JSON, не открывает ссылки и не исполняет код.
Интерфейс и совместимость последующих версий ещё не обещаны.
"""
from __future__ import annotations

import json
import math
import os
import re
import stat
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from .entities import SCHEMA_VERSION, Project
from .project_io import ProjectIOError, _read_project_bytes, _unique_object, project_to_json
from .project_limits import MAX_PROJECT_BYTES

VERSION = "0.1"
MAX_PARTS = 256
MAX_INSTANCES = 1024
MAX_MM = 1_000_000.0  # защитная граница прототипа, не инженерный допуск
_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")


class KimFormatError(ValueError):
    """Некорректный или неподдерживаемый документ KIM."""


def _keys(value: Any, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise KimFormatError("invalid document fields")
    return value


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or not value.isprintable():
        raise KimFormatError("invalid name")
    return value


def _id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise KimFormatError("invalid identifier")
    return value


def _number(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise KimFormatError("invalid number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise KimFormatError("invalid number") from error
    if not math.isfinite(number) or abs(number) > MAX_MM or (positive and number <= 0):
        raise KimFormatError("number outside prototype bounds")
    return number


def _part(data: Any) -> None:
    doc = _keys(data, {"format", "version", "id", "name", "units", "geometry"})
    if doc["format"] != "kim-part" or doc["version"] != VERSION or doc["units"] != "mm":
        raise KimFormatError("unsupported part format, version or units")
    _id(doc["id"])
    _name(doc["name"])
    shape = _keys(doc["geometry"], {"kind", "radius_mm", "length_mm"})
    if shape["kind"] != "prototype_cylinder":
        raise KimFormatError("unsupported geometry")
    _number(shape["radius_mm"], positive=True)
    _number(shape["length_mm"], positive=True)


def _scheme(data: Any) -> None:
    if data is None:
        return
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise KimFormatError("unsupported suspension scheme")
    try:
        # Require a complete, losslessly re-serializable current project; do
        # not silently drop unknown fields or fill missing ones on roundtrip.
        json.dumps(data, allow_nan=False)
        project = Project.from_dict(data)
        if project.to_dict() != data:
            raise ValueError("incomplete or incompatible scheme")
        json.dumps(project.to_dict(), allow_nan=False)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise KimFormatError("invalid or incomplete suspension scheme") from error


def _assembly(data: Any) -> None:
    doc = _keys(data, {"format", "version", "name", "units", "frame", "scheme", "parts", "instances"})
    if (doc["format"] != "kima-assembly" or doc["version"] != VERSION or doc["units"] != "mm" or
            doc["frame"] != "unregistered"):
        raise KimFormatError("unsupported assembly format, version, units or frame")
    _name(doc["name"])
    _scheme(doc["scheme"])
    parts = doc["parts"]
    instances = doc["instances"]
    if not isinstance(parts, list) or len(parts) > MAX_PARTS:
        raise KimFormatError("invalid parts")
    if not isinstance(instances, list) or len(instances) > MAX_INSTANCES:
        raise KimFormatError("invalid instances")
    part_ids: set[str] = set()
    for part in parts:
        _part(part)
        key = _id(part["id"])
        if key in part_ids:
            raise KimFormatError("duplicate part identifier")
        part_ids.add(key)
    instance_ids: set[str] = set()
    for instance in instances:
        item = _keys(instance, {"id", "part_id", "translation_mm"})
        key = _id(item["id"])
        if key in instance_ids or _id(item["part_id"]) not in part_ids:
            raise KimFormatError("duplicate instance or missing part")
        instance_ids.add(key)
        translation = item["translation_mm"]
        if not isinstance(translation, list) or len(translation) != 3:
            raise KimFormatError("invalid translation")
        for coordinate in translation:
            _number(coordinate)


def make_test_cylinder(identifier: str, name: str, radius_mm: float, length_mm: float) -> dict[str, Any]:
    """Одна демонстрационная цилиндрическая деталь вдоль локальной оси +Z."""
    result = {"format": "kim-part", "version": VERSION, "id": identifier, "name": name, "units": "mm",
              "geometry": {"kind": "prototype_cylinder", "radius_mm": radius_mm, "length_mm": length_mm}}
    _part(result)
    return result


def make_assembly(name: str, parts: list[dict[str, Any]], instances: list[dict[str, Any]],
                  scheme: Project | None = None) -> dict[str, Any]:
    """Схема и детали копируются; сборка не привязана к системе автомобиля."""
    try:
        raw_scheme = json.loads(project_to_json(scheme), object_pairs_hook=_unique_object) if scheme else None
        # JSON copy prevents subsequent edits from mutating the saved snapshot.
        data = json.loads(json.dumps({"format": "kima-assembly", "version": VERSION, "name": name,
                                     "units": "mm", "frame": "unregistered", "scheme": raw_scheme,
                                     "parts": parts, "instances": instances}, allow_nan=False))
        _assembly(data)
        return data
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise KimFormatError("cannot create assembly") from error


def _validate(data: Any, kind: str) -> None:
    if kind == "part":
        _part(data)
    elif kind == "assembly":
        _assembly(data)
    else:
        raise KimFormatError("unknown kind")


def _suffix(path: Path, kind: str) -> None:
    suffix = {"part": ".kim", "assembly": ".kima"}.get(kind)
    if suffix is None or path.suffix.lower() != suffix:
        raise KimFormatError("incorrect file extension")


def read_document(path: str | Path, kind: str) -> dict[str, Any]:
    """Без исполняемых данных, распаковки или автоматического чтения ссылок."""
    source = Path(path)
    _suffix(source, kind)
    try:
        raw = _read_project_bytes(source).decode("utf-8")
        data = json.loads(raw, object_pairs_hook=_unique_object)
        # Includes unrecognized nested values; rejects overflow and NaN.
        json.dumps(data, allow_nan=False)
        _validate(data, kind)
        return data  # type: ignore[no-any-return]
    except (ProjectIOError, OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as error:
        raise KimFormatError("cannot read KIM document") from error


def write_document(path: str | Path, kind: str, data: dict[str, Any]) -> Path:
    """Проверка перед атомарной заменой; пользователь обязан иметь резервную копию."""
    target = Path(path)
    _suffix(target, kind)
    temporary: str | None = None
    try:
        _validate(data, kind)
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        if len(content) > MAX_PROJECT_BYTES:
            raise KimFormatError("document exceeds 64 MiB")
        # Do not follow a file symlink: it may point at an unrelated project.
        if target.is_symlink():
            raise KimFormatError("symlink destination is not supported")
        destination = target.resolve()
        try:
            existing = destination.stat()
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise KimFormatError("destination is not a regular file")
        with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent,
                                         prefix=".kim-document-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if existing is not None and os.name != "nt":
            os.chmod(temporary, stat.S_IMODE(existing.st_mode))
        os.replace(temporary, destination)
        temporary = None
        return target
    except (OSError, UnicodeError, TypeError, ValueError, OverflowError, RuntimeError, RecursionError) as error:
        raise KimFormatError("cannot write KIM document") from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
