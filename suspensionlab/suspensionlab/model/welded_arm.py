"""Исследовательская структура сварного рычага KIMA 0.2/0.3, не рабочая документация.

Сборка намеренно неполная: заданы два прототипа труб, остальные изделия и
кандидаты сварных соединений представлены незаполненными позициями.
"""
from __future__ import annotations

import json
from typing import Any

from .entities import Project
from .kim_format import (
    BENT_PART_VERSION,
    KimFormatError,
    _keys,
    _lower_arm_source,
    _name,
    _part,
    _scheme,
    compare_lower_arm_source,
    make_arm_tube,
)
from .project_io import project_to_json

VERSION = "0.2"
BENT_VERSION = "0.3"
DAMPER_CHOICES = ("unknown", "required", "not_required")


def _node(identifier: str, role: str, kind: str, parent: str | None, part: str | None = None) -> dict[str, Any]:
    return {"id": identifier, "role": role, "kind": kind, "parent": parent, "part_id": part}


def _nodes(damper: str) -> list[dict[str, Any]]:
    nodes = [
        _node("arm", "complete_arm", "assembly", None),
        _node("weldment", "weldment", "assembly", "arm"),
        _node("tube_front", "front_tube", "part", "weldment", "tube_front"),
        _node("tube_rear", "rear_tube", "part", "weldment", "tube_rear"),
        _node("housing_front", "front_bushing_housing", "unresolved", "weldment"),
        _node("housing_rear", "rear_bushing_housing", "unresolved", "weldment"),
        _node("ball_bracket", "ball_joint_bracket", "unresolved", "weldment"),
        _node("ball_joint", "ball_joint", "purchased_unselected", "arm"),
        _node("bushing_front", "front_silent_block", "purchased_unselected", "arm"),
        _node("bushing_rear", "rear_silent_block", "purchased_unselected", "arm"),
        _node("fasteners", "fasteners", "purchased_unselected", "arm"),
    ]
    if damper == "required":
        nodes.append(_node("damper_bracket", "damper_bracket", "unresolved", "weldment"))
    return nodes


def _welds(damper: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [
        {"a": "tube_front", "b": "housing_front", "status": "needs_design"},
        {"a": "tube_rear", "b": "housing_rear", "status": "needs_design"},
        {"a": "tube_front", "b": "ball_bracket", "status": "needs_design"},
        {"a": "tube_rear", "b": "ball_bracket", "status": "needs_design"},
    ]
    if damper == "required":
        # Location and connected member must be selected, never invented.
        result.append({"a": "damper_bracket", "b": None, "status": "needs_design"})
    return result


def validate_welded_arm(data: Any) -> None:
    """Отклоняет неизвестные поля и невосстанавливаемые несоответствия графа."""
    doc = _keys(data, {"format", "version", "name", "units", "frame", "scheme", "damper_mount", "parts", "nodes", "welds"})
    if (doc["format"] != "kima-assembly" or doc["version"] not in (VERSION, BENT_VERSION) or doc["units"] != "mm" or
            doc["frame"] != "vehicle_front_left_snapshot"):
        raise KimFormatError("unsupported weldment format, units or frame")
    _name(doc["name"])
    if doc["scheme"] is None:
        raise KimFormatError("weldment requires a scheme snapshot")
    _scheme(doc["scheme"])
    damper = doc["damper_mount"]
    if damper not in DAMPER_CHOICES:
        raise KimFormatError("unknown damper choice")
    # Exact canonical graph: duplicate/missing/unknown nodes or welds cannot be
    # silently discarded by this early, intentionally non-general prototype.
    if doc["nodes"] != _nodes(damper) or doc["welds"] != _welds(damper):
        raise KimFormatError("unsupported or inconsistent weldment graph")
    parts = doc["parts"]
    if not isinstance(parts, list) or len(parts) != 2:
        raise KimFormatError("two distinct tube definitions required")
    for index, (identifier, leg) in enumerate((("tube_front", "front"), ("tube_rear", "rear"))):
        part = parts[index]
        _part(part)
        allowed = ("prototype_arm_tube",) if doc["version"] == VERSION else ("prototype_arm_tube", "prototype_arm_bent_tube")
        if part["id"] != identifier or part["geometry"]["kind"] not in allowed or part["geometry"]["leg"] != leg:
            raise KimFormatError("invalid tube reference")
    if doc["version"] == BENT_VERSION and not any(p["geometry"]["kind"] == "prototype_arm_bent_tube" for p in parts):
        raise KimFormatError("bent version requires at least one bent tube")
    a, b = (part["geometry"] for part in parts)
    if any(a[key] != b[key] for key in ("radius_mm", "wall_mm", "source")):
        raise KimFormatError("inconsistent tube definitions")


def make_welded_arm(project: Project, radius_mm: float, wall_mm: float, damper: str, *,
                    bends: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Снимок сборки; не выбирает направления осей втулок или покупные изделия."""
    if damper not in DAMPER_CHOICES:
        raise KimFormatError("invalid damper choice")
    front = make_arm_tube("tube_front", "Передняя труба", project, "front", radius_mm, wall_mm)
    rear = make_arm_tube("tube_rear", "Задняя труба", project, "rear", radius_mm, wall_mm)
    if bends is None:
        bends = {}
    if not isinstance(bends, dict) or any(key not in ("front", "rear") for key in bends):
        raise KimFormatError("invalid tube bend selection")
    for leg, part in (("front", front), ("rear", rear)):
        if leg in bends:
            bend = _keys(bends[leg], {"vertex_mm", "radius_mm"})
            if not isinstance(bend["vertex_mm"], list):
                raise KimFormatError("bend vertex must be a coordinate list")
            part["version"] = BENT_PART_VERSION
            part["geometry"].update(kind="prototype_arm_bent_tube", bend_vertex_mm=list(bend["vertex_mm"]),
                                    bend_radius_mm=bend["radius_mm"])
            _part(part)
    try:
        scheme = json.loads(project_to_json(project))
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise KimFormatError("cannot capture project") from error
    doc: dict[str, Any] = {"format": "kima-assembly", "version": BENT_VERSION if bends else VERSION,
                           "name": "Передний нижний левый рычаг — исследовательский черновик",
                           "units": "mm", "frame": "vehicle_front_left_snapshot", "scheme": scheme,
                           "damper_mount": damper, "parts": [front, rear],
                           "nodes": _nodes(damper), "welds": _welds(damper)}
    validate_welded_arm(doc)
    return doc


def weldment_source_matches(document: dict[str, Any]) -> bool:
    """Только совпадение типа и трёх округлённых точек со снимком внутри файла."""
    validate_welded_arm(document)
    project = Project.from_dict(document["scheme"])
    return all(compare_lower_arm_source(part, project) for part in document["parts"])


def weldment_bends(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Возвращает независимую копию явно заданных параметров изгибов."""
    validate_welded_arm(document)
    return {part["geometry"]["leg"]: {"vertex_mm": list(part["geometry"]["bend_vertex_mm"]),
                                       "radius_mm": part["geometry"]["bend_radius_mm"]}
            for part in document["parts"] if part["geometry"]["kind"] == "prototype_arm_bent_tube"}


def rebuild_welded_arm(document: dict[str, Any], project: Project, *,
                       bends: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Новый снимок на той же схеме и с теми же размерами; исходник не меняется."""
    validate_welded_arm(document)
    geometry = document["parts"][0]["geometry"]
    if _lower_arm_source(project)["suspension_type"] != geometry["source"]["suspension_type"]:
        raise KimFormatError("suspension type changed")
    if bends is None:
        bends = weldment_bends(document)
    result = make_welded_arm(project, geometry["radius_mm"], geometry["wall_mm"], document["damper_mount"], bends=bends)
    result["name"] = document["name"]
    for old_part, new_part in zip(document["parts"], result["parts"], strict=True):
        new_part["name"] = old_part["name"]
    validate_welded_arm(result)
    return result


def convert_legacy_tubes(part: dict[str, Any], project: Project, damper: str) -> dict[str, Any]:
    """Явно преобразовать старый двухтрубный эксперимент, не меняя его файл."""
    _part(part)
    geometry = part["geometry"]
    if geometry["kind"] != "prototype_lower_arm_tubes" or not compare_lower_arm_source(part, project):
        raise KimFormatError("legacy tube source does not match current scheme")
    return make_welded_arm(project, geometry["radius_mm"], geometry["wall_mm"], damper)


def preview_rebuild_welded_arm(document: dict[str, Any], project: Project, *,
                               bends: dict[str, dict[str, Any]] | None = None) -> tuple[dict[str, Any], bool]:
    """Кандидат без записи; совпадение не доказывает происхождение проекта.

    Внутренне устаревший исходник блокируется: перед автоматическим
    построением его несоответствие нужно разрешить отдельным инструментом.
    """
    if not weldment_source_matches(document):
        raise KimFormatError("assembly source differs from saved scheme")
    matches = all(compare_lower_arm_source(part, project) for part in document["parts"])
    return rebuild_welded_arm(document, project, bends=bends), matches


def weldment_centerlines(document: dict[str, Any]) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    """Осевые линии для условной проекции XY; дуги отображаются с приближением."""
    from .bent_tube import make_bend_path

    validate_welded_arm(document)
    paths = []
    for part in document["parts"]:
        geometry = part["geometry"]
        points = geometry["source"]["coordinates_mm"]
        start, end = points[0 if geometry["leg"] == "front" else 1], points[2]
        if geometry["kind"] == "prototype_arm_bent_tube":
            path = make_bend_path(start, geometry["bend_vertex_mm"], end,
                                  geometry["bend_radius_mm"], geometry["radius_mm"])
            paths.append(path.sample())
        else:
            paths.append((tuple(start), tuple(end)))
    return tuple(paths)
