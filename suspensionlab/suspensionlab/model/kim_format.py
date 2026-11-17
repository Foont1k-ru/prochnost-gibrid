"""Исследовательские файлы KIM: точный контракт прототипа, не готовый CAD.

Версия 0.1 поддерживает тестовый цилиндр, условный рычаг и переносы. Сборка
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
BENT_PART_VERSION = "0.2"
MAX_PARTS = 256
MAX_INSTANCES = 1024
MAX_MM = 1_000_000.0  # защитная граница прототипа, не инженерный допуск
_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")
LOWER_ARM_POINTS = ("lca_f_in", "lca_r_in", "lbj")
LOWER_ARM_TYPES = ("double_wishbone", "macpherson_front")
MIN_PROTOTYPE_LENGTH_MM = 0.01  # устойчивость построения, не допуск детали


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
    if doc["format"] != "kim-part" or doc["version"] not in (VERSION, BENT_PART_VERSION) or doc["units"] != "mm":
        raise KimFormatError("unsupported part format, version or units")
    _id(doc["id"])
    _name(doc["name"])
    shape = doc["geometry"]
    if not isinstance(shape, dict):
        raise KimFormatError("invalid geometry")
    if (shape.get("kind") == "prototype_arm_bent_tube") != (doc["version"] == BENT_PART_VERSION):
        raise KimFormatError("part version does not match geometry")
    if shape.get("kind") == "prototype_cylinder":
        _keys(shape, {"kind", "radius_mm", "length_mm"})
        _number(shape["radius_mm"], positive=True)
        _number(shape["length_mm"], positive=True)
    elif shape.get("kind") in ("prototype_lower_arm_rods", "prototype_lower_arm_tubes", "prototype_arm_tube", "prototype_arm_bent_tube"):
        keys = {"kind", "radius_mm", "source"}
        if shape["kind"] in ("prototype_lower_arm_tubes", "prototype_arm_tube", "prototype_arm_bent_tube"):
            keys.add("wall_mm")
        if shape["kind"] in ("prototype_arm_tube", "prototype_arm_bent_tube"):
            keys.add("leg")
        if shape["kind"] == "prototype_arm_bent_tube":
            keys.update({"bend_vertex_mm", "bend_radius_mm"})
        _keys(shape, keys)
        radius = _number(shape["radius_mm"], positive=True)
        if radius < MIN_PROTOTYPE_LENGTH_MM:
            raise KimFormatError("radius too small for prototype")
        if shape["kind"] in ("prototype_arm_tube", "prototype_arm_bent_tube") and shape["leg"] not in ("front", "rear"):
            raise KimFormatError("unsupported tube leg")
        if shape["kind"] in ("prototype_lower_arm_tubes", "prototype_arm_tube", "prototype_arm_bent_tube"):
            wall = _number(shape["wall_mm"], positive=True)
            if wall < MIN_PROTOTYPE_LENGTH_MM or radius - wall < MIN_PROTOTYPE_LENGTH_MM:
                raise KimFormatError("invalid tube wall or inner radius")
        source = _keys(shape["source"], {"axle", "side", "suspension_type", "point_codes", "coordinates_mm"})
        if (source["axle"] != "front" or source["side"] != "left" or
                source["suspension_type"] not in LOWER_ARM_TYPES or
                source["point_codes"] != list(LOWER_ARM_POINTS)):
            raise KimFormatError("unsupported arm source")
        coords = source["coordinates_mm"]
        if not isinstance(coords, list) or len(coords) != 3:
            raise KimFormatError("invalid arm points")
        points: list[tuple[float, float, float]] = []
        for point in coords:
            if not isinstance(point, list) or len(point) != 3:
                raise KimFormatError("invalid arm point")
            points.append((_number(point[0]), _number(point[1]), _number(point[2])))
        # All three distinct; prevent degenerate axes in the CAD kernel.
        if any(math.dist(points[i], points[j]) < MIN_PROTOTYPE_LENGTH_MM
               for i, j in ((0, 1), (0, 2), (1, 2))):
            raise KimFormatError("coincident arm points")
        if shape["kind"] == "prototype_arm_bent_tube":
            if not isinstance(shape["bend_vertex_mm"], list):
                raise KimFormatError("bend vertex must be a coordinate list")
            from .bent_tube import BentTubeError, make_bend_path

            try:
                make_bend_path(points[0 if shape["leg"] == "front" else 1], shape["bend_vertex_mm"],
                               points[2], shape["bend_radius_mm"], shape["radius_mm"])
            except BentTubeError as error:
                raise KimFormatError("invalid bent tube path") from error
    else:
        raise KimFormatError("unsupported geometry")


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
    if isinstance(data, dict) and data.get("version") in ("0.2", "0.3"):
        from .welded_arm import validate_welded_arm

        validate_welded_arm(data)
        return
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


def _lower_arm_source(project: Project) -> dict[str, Any]:
    """Данные только из того же округлённого снимка, который хранится в проекте."""
    try:
        data = json.loads(project_to_json(project), object_pairs_hook=_unique_object)
        axle = data["front_axle"]
        suspension_type = axle["type"]
        if suspension_type not in LOWER_ARM_TYPES:
            raise KimFormatError("unsupported front suspension")
        points = axle["hardpoints"]
        coordinates = [[points[code][axis] for axis in ("x", "y", "z")] for code in LOWER_ARM_POINTS]
        return {"axle": "front", "side": "left", "suspension_type": suspension_type,
                "point_codes": list(LOWER_ARM_POINTS), "coordinates_mm": coordinates}
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise KimFormatError("cannot capture suspension points") from error


def make_lower_arm_prototype(identifier: str, name: str, project: Project, radius_mm: float) -> dict[str, Any]:
    """Два условных стержня по трём сохранённым точкам, только передняя левая сторона."""
    part = {"format": "kim-part", "version": VERSION, "id": identifier, "name": name, "units": "mm",
            "geometry": {"kind": "prototype_lower_arm_rods", "radius_mm": radius_mm,
                         "source": _lower_arm_source(project)}}
    _part(part)
    return part


def make_lower_arm_tube_prototype(identifier: str, name: str, project: Project,
                                   radius_mm: float, wall_mm: float) -> dict[str, Any]:
    """Две не соединённые пустотелые трубы, не конструкция для изготовления."""
    part = {"format": "kim-part", "version": VERSION, "id": identifier, "name": name, "units": "mm",
            "geometry": {"kind": "prototype_lower_arm_tubes", "radius_mm": radius_mm,
                         "wall_mm": wall_mm, "source": _lower_arm_source(project)}}
    _part(part)
    return part


def make_arm_tube(identifier: str, name: str, project: Project, leg: str,
                  radius_mm: float, wall_mm: float) -> dict[str, Any]:
    """Отдельный неподрезанный трубный элемент с привязкой к снимку схемы."""
    part = {"format": "kim-part", "version": VERSION, "id": identifier, "name": name, "units": "mm",
            "geometry": {"kind": "prototype_arm_tube", "leg": leg, "radius_mm": radius_mm,
                         "wall_mm": wall_mm, "source": _lower_arm_source(project)}}
    _part(part)
    return part


def rebuild_lower_arm_prototype(part: dict[str, Any], project: Project) -> dict[str, Any]:
    """Новый снимок по тем же параметрам; тип схемы менять не разрешается."""
    _part(part)
    shape = part["geometry"]
    kind = shape["kind"]
    if kind not in ("prototype_lower_arm_rods", "prototype_lower_arm_tubes"):
        raise KimFormatError("not a lower arm prototype")
    if _lower_arm_source(project)["suspension_type"] != shape["source"]["suspension_type"]:
        raise KimFormatError("suspension type changed; create a new prototype")
    if kind == "prototype_lower_arm_tubes":
        return make_lower_arm_tube_prototype(part["id"], part["name"], project, shape["radius_mm"], shape["wall_mm"])
    return make_lower_arm_prototype(part["id"], part["name"], project, shape["radius_mm"])


def compare_lower_arm_source(part: dict[str, Any], project: Project) -> bool:
    """Сравнить тип и три точки, не другие параметры, и ничего не обновлять."""
    _part(part)
    geometry = part["geometry"]
    if geometry["kind"] not in ("prototype_lower_arm_rods", "prototype_lower_arm_tubes", "prototype_arm_tube", "prototype_arm_bent_tube"):
        raise KimFormatError("not a lower arm prototype")
    try:
        current = _lower_arm_source(project)
    except KimFormatError:
        return False
    return geometry["source"] == current


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


def inspect_assembly_arm_sources(document: dict[str, Any]) -> dict[str, str]:
    """Сравнить сохранённые рычаги со схемой В ЭТОМ снимке; не с живым проектом.

    'match' — совпадают три округлённые точки и тип; 'different' — различие;
    'no_scheme' — схемы в сборке нет. Никакого перестроения не происходит.
    """
    _assembly(document)
    scheme = Project.from_dict(document["scheme"]) if document["scheme"] is not None else None
    result: dict[str, str] = {}
    for part in document["parts"]:
        if part["geometry"]["kind"] not in ("prototype_lower_arm_rods", "prototype_lower_arm_tubes", "prototype_arm_tube", "prototype_arm_bent_tube"):
            continue
        if scheme is None:
            result[part["id"]] = "no_scheme"
        elif compare_lower_arm_source(part, scheme):
            result[part["id"]] = "match"
        else:
            result[part["id"]] = "different"
    return result


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


def write_document(path: str | Path, kind: str, data: dict[str, Any], *, overwrite: bool = True) -> Path:
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
        if overwrite:
            os.replace(temporary, destination)
            temporary = None
        else:
            # Atomic create-if-absent on the same filesystem, never replacing
            # an existing file or a file created while the dialog was open.
            os.link(temporary, destination)
            os.unlink(temporary)
            temporary = None
        return target
    except (OSError, UnicodeError, TypeError, ValueError, OverflowError, RuntimeError, RecursionError) as error:
        raise KimFormatError("cannot write KIM document") from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
