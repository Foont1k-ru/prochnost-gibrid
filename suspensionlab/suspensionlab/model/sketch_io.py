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
from .sketch_contours import ordered_contour_indices
from .sketch_draft import (
    LIMIT_MM,
    MAX_DIMENSIONS,
    MAX_ENTITIES,
    Dimension,
    Entity,
    Kind,
    Point,
    make_entity,
    validate_dimension,
)
from .sketch_extrude_settings import ExtrusionSettings, HoleOverride, hole_entry_side

MAX_BYTES = 2 * 1024 * 1024
SUFFIX = ".slsketch"


class SketchIOError(ValueError):
    """Повреждённый эскиз или ошибка ввода-вывода."""


@dataclass(frozen=True)
class SketchDocument:
    plane: str
    offset_mm: float
    entities: tuple[Entity, ...]
    dimensions: tuple[Dimension, ...] = ()
    extrusion: ExtrusionSettings = ExtrusionSettings()


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
    if not isinstance(value, dict):
        raise SketchIOError("Некорректная структура эскиза")
    version = value.get("version")
    expected = {"format", "version", "units", "plane", "offset_mm", "entities"}
    if version in ("3", "4", "5", "6"):
        expected.add("dimensions")
    if version == "6":
        expected.add("extrusion")
    if set(value) != expected:
        raise SketchIOError("Некорректная структура эскиза")
    if value["format"] != "suspensionlab-sketch" or version not in ("1", "2", "3", "4", "5", "6") or value["units"] != "mm":
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
            if version not in ("2", "3", "4", "5", "6") or set(item) != {"kind", "start", "end", "sweep_deg"}:
                raise SketchIOError("Неподдерживаемая дуга")
            sweep = _number(item["sweep_deg"])
        else:
            if set(item) != {"kind", "start", "end"}:
                raise SketchIOError("Некорректный элемент")
            sweep = None
        entities.append(make_entity(cast(Kind, kind), _point(item["start"]), _point(item["end"]), sweep))
    dimensions: list[Dimension] = []
    if version in ("3", "4", "5", "6"):
        items = value["dimensions"]
        if not isinstance(items, list) or len(items) > MAX_DIMENSIONS:
            raise SketchIOError("Некорректное количество размеров")
        for item in items:
            if not isinstance(item, dict):
                raise SketchIOError("Некорректный размер")
            fields = {"entity_index", "position", "mode"}
            if item.get("mode") == "between":
                if version not in ("5", "6"):
                    raise SketchIOError("Угол между отрезками требует версию 5")
                fields.add("other_index")
            if set(item) != fields:
                raise SketchIOError("Некорректный размер")
            if item["mode"] == "inclination" and version not in ("4", "5", "6"):
                raise SketchIOError("Наклон отрезка требует версию 4 или 5")
            dimensions.append(validate_dimension(Dimension(item["entity_index"], _point(item["position"]),
                                                           item["mode"], item.get("other_index")), tuple(entities)))
    extrusion = ExtrusionSettings()
    if version == "6":
        settings = value["extrusion"]
        if not isinstance(settings, dict) or set(settings) != {"direction", "hole_depth", "hole_side", "hole_overrides"}:
            raise SketchIOError("Некорректные настройки выдавливания")
        direction, side = settings["direction"], settings["hole_side"]
        hole_entry_side(direction, side)

        def stored_depth(raw: Any) -> float:
            depth = _number(raw)
            if depth < 0 or round(depth, 3) != depth:
                raise SketchIOError("Некорректная глубина отверстия")
            return depth

        raw_overrides = settings["hole_overrides"]
        if not isinstance(raw_overrides, list) or len(raw_overrides) > min(len(entities), 300):
            raise SketchIOError("Некорректные настройки отверстий")
        overrides: list[HoleOverride] = []
        if raw_overrides:
            contours = ordered_contour_indices(tuple(entities))
            if len(contours) < 2:
                raise SketchIOError("Для настроек отверстий нужны замкнутые контуры")
            keys = {min(index for index, _ in contour) for contour in contours}
            seen: set[int] = set()
            for item in raw_overrides:
                if not isinstance(item, dict) or set(item) != {"entity_index", "depth", "side"}:
                    raise SketchIOError("Некорректные настройки отверстия")
                index, entry = item["entity_index"], item["side"]
                if isinstance(index, bool) or not isinstance(index, int) or index not in keys or index in seen:
                    raise SketchIOError("Некорректный или повторный контур отверстия")
                hole_entry_side(direction, entry)
                overrides.append((index, stored_depth(item["depth"]), entry))
                seen.add(index)
            if [item[0] for item in overrides] != sorted(seen):
                raise SketchIOError("Настройки отверстий должны быть упорядочены")
        extrusion = ExtrusionSettings(direction, stored_depth(settings["hole_depth"]), side, tuple(overrides))
    return SketchDocument(plane, offset, tuple(entities), tuple(dimensions), extrusion)


def _as_data(document: SketchDocument) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for entity in document.entities:
        item: dict[str, Any] = {"kind": entity.kind, "start": list(entity.start), "end": list(entity.end)}
        if entity.kind == "arc":
            item["sweep_deg"] = entity.sweep_deg
        items.append(item)
    data: dict[str, Any] = {"format": "suspensionlab-sketch",
                            "version": ("6" if document.extrusion != ExtrusionSettings() else
                                        "5" if any(d.mode == "between" for d in document.dimensions) else
                                        "4" if any(d.mode == "inclination" for d in document.dimensions) else
                                        "3" if document.dimensions else "2" if any(e.kind == "arc" for e in document.entities) else "1"),
                            "units": "mm", "plane": document.plane, "offset_mm": document.offset_mm,
                            "entities": items}
    if document.dimensions or data["version"] == "6":
        data["dimensions"] = [{"entity_index": d.entity_index, "position": list(d.position), "mode": d.mode,
                               **({"other_index": d.other_index} if d.mode == "between" else {})}
                              for d in document.dimensions]
    if data["version"] == "6":
        settings = document.extrusion
        data["extrusion"] = {"direction": settings.direction, "hole_depth": settings.hole_depth,
                             "hole_side": settings.hole_side,
                             "hole_overrides": [{"entity_index": i, "depth": depth, "side": side}
                                                for i, depth, side in settings.hole_overrides]}
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
