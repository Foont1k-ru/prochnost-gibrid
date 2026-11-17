"""Версионированный самостоятельный документ эскиза без внешних ссылок.

Сохранение намеренно только в новый файл: атомарное создание не затирает
ни существующий проект, ни изменённый другим приложением эскиз.
"""
from __future__ import annotations

import json
import math
import os
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .project_io import _unique_object
from .sketch_draft import LIMIT_MM, MAX_ENTITIES, Entity, Kind, Point, make_entity

MAX_BYTES = 2 * 1024 * 1024
SUFFIX = ".slsketch"


class SketchIOError(ValueError):
    """Повреждённый эскиз или ошибка ввода-вывода."""


@dataclass(frozen=True)
class SketchDocument:
    plane: str
    offset_mm: float
    entities: tuple[Entity, ...]


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SketchIOError("Ожидалось число")
    try:
        result = float(value)
    except OverflowError as exc:
        raise SketchIOError("Число вне диапазона") from exc
    if not math.isfinite(result) or abs(result) > LIMIT_MM:
        raise SketchIOError("Число вне допустимого диапазона")
    return result


def _point(value: Any) -> Point:
    if not isinstance(value, list) or len(value) != 2:
        raise SketchIOError("Некорректная точка")
    return _number(value[0]), _number(value[1])


def _parse(value: Any) -> SketchDocument:
    if not isinstance(value, dict) or set(value) != {"format", "version", "units", "plane", "offset_mm", "entities"}:
        raise SketchIOError("Некорректная структура эскиза")
    if value["format"] != "suspensionlab-sketch" or value["version"] not in ("1", "2") or value["units"] != "mm":
        raise SketchIOError("Неподдерживаемая версия или единицы")
    plane = value["plane"]
    if plane not in ("XY", "XZ", "YZ"):
        raise SketchIOError("Неизвестная плоскость")
    offset = _number(value["offset_mm"])
    if round(offset, 3) != offset:
        raise SketchIOError("Смещение допускает не более трёх знаков после запятой")
    items = value["entities"]
    if not isinstance(items, list) or len(items) > MAX_ENTITIES:
        raise SketchIOError("Некорректное количество элементов")
    entities: list[Entity] = []
    for item in items:
        if not isinstance(item, dict):
            raise SketchIOError("Некорректный элемент")
        kind = item.get("kind")
        if kind not in ("line", "circle", "arc"):
            raise SketchIOError("Неизвестный элемент")
        if kind == "arc":
            if value["version"] != "2" or set(item) != {"kind", "start", "end", "sweep_deg"}:
                raise SketchIOError("Неподдерживаемая дуга")
            sweep = _number(item["sweep_deg"])
        else:
            if set(item) != {"kind", "start", "end"}:
                raise SketchIOError("Некорректный элемент")
            sweep = None
        entities.append(make_entity(cast(Kind, kind), _point(item["start"]), _point(item["end"]), sweep))
    return SketchDocument(plane, offset, tuple(entities))


def _as_data(document: SketchDocument) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for entity in document.entities:
        item: dict[str, Any] = {"kind": entity.kind, "start": list(entity.start), "end": list(entity.end)}
        if entity.kind == "arc":
            item["sweep_deg"] = entity.sweep_deg
        items.append(item)
    data: dict[str, Any] = {"format": "suspensionlab-sketch",
                            "version": "2" if any(e.kind == "arc" for e in document.entities) else "1",
                            "units": "mm", "plane": document.plane, "offset_mm": document.offset_mm,
                            "entities": items}
    _parse(data)
    return data


def _suffix(path: Path) -> None:
    if path.suffix.lower() != SUFFIX:
        raise SketchIOError("Используйте расширение .slsketch")


def read_sketch(path: str | Path) -> SketchDocument:
    source = Path(path)
    _suffix(source)
    try:
        # Validate the opened descriptor, not just the path, and avoid FIFO blocking.
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(source, flags)
        try:
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise SketchIOError("Файл не является обычным файлом")
                raw = handle.read(MAX_BYTES + 1)
        finally:
            if fd != -1:
                os.close(fd)
        if len(raw) > MAX_BYTES:
            raise SketchIOError("Слишком большой файл")
        return _parse(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid constant"))))
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise SketchIOError(f"Не удалось открыть эскиз: {exc}") from exc


def write_new_sketch(path: str | Path, document: SketchDocument) -> Path:
    target = Path(path)
    _suffix(target)
    temporary: str | None = None
    try:
        content = json.dumps(_as_data(document), ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        if len(content) > MAX_BYTES:
            raise SketchIOError("Слишком большой эскиз")
        with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=".sketch-", suffix=".tmp",
                                         delete=False) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # link is atomic create-if-absent; never follows or replaces the target.
        os.link(temporary, target)
        return target
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RuntimeError, RecursionError) as exc:
        raise SketchIOError(f"Не удалось сохранить новый эскиз: {exc}") from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
