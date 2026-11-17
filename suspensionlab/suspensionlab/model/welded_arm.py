"""Исследовательская структура сварного рычага KIMA 0.2, не рабочая документация.

Сборка намеренно неполная: заданы два прототипа труб, остальные изделия и
кандидаты сварных соединений представлены незаполненными позициями.
"""
from __future__ import annotations

import json
from typing import Any

from .entities import Project
from .kim_format import (
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
    if (doc["format"] != "kima-assembly" or doc["version"] != VERSION or doc["units"] != "mm" or
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
        if part["id"] != identifier or part["geometry"]["kind"] != "prototype_arm_tube" or part["geometry"]["leg"] != leg:
            raise KimFormatError("invalid tube reference")
    a, b = (part["geometry"] for part in parts)
    if any(a[key] != b[key] for key in ("radius_mm", "wall_mm", "source")):
        raise KimFormatError("inconsistent tube definitions")


def make_welded_arm(project: Project, radius_mm: float, wall_mm: float, damper: str) -> dict[str, Any]:
    """Снимок сборки; не выбирает направления осей втулок или покупные изделия."""
    if damper not in DAMPER_CHOICES:
        raise KimFormatError("invalid damper choice")
    front = make_arm_tube("tube_front", "Передняя труба", project, "front", radius_mm, wall_mm)
    rear = make_arm_tube("tube_rear", "Задняя труба", project, "rear", radius_mm, wall_mm)
    try:
        scheme = json.loads(project_to_json(project))
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise KimFormatError("cannot capture project") from error
    doc: dict[str, Any] = {"format": "kima-assembly", "version": VERSION,
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


def rebuild_welded_arm(document: dict[str, Any], project: Project) -> dict[str, Any]:
    """Новый снимок на той же схеме и с теми же размерами; исходник не меняется."""
    validate_welded_arm(document)
    geometry = document["parts"][0]["geometry"]
    if _lower_arm_source(project)["suspension_type"] != geometry["source"]["suspension_type"]:
        raise KimFormatError("suspension type changed")
    result = make_welded_arm(project, geometry["radius_mm"], geometry["wall_mm"], document["damper_mount"])
    result["name"] = document["name"]
    validate_welded_arm(result)
    return result


def convert_legacy_tubes(part: dict[str, Any], project: Project, damper: str) -> dict[str, Any]:
    """Явно преобразовать старый двухтрубный эксперимент, не меняя его файл."""
    _part(part)
    geometry = part["geometry"]
    if geometry["kind"] != "prototype_lower_arm_tubes" or not compare_lower_arm_source(part, project):
        raise KimFormatError("legacy tube source does not match current scheme")
    return make_welded_arm(project, geometry["radius_mm"], geometry["wall_mm"], damper)
