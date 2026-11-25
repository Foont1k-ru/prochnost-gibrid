"""Изолированные численные проверки CAD-тел фиксированного рычага."""
from __future__ import annotations

import json
import math
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

from ..model.fixed_arm_housings import PREVIEW_FORMAT, validate_housing_preview
from ..model.project_io import _read_project_bytes, _unique_object
from ..model.welded_arm import weldment_source_matches
from .cad_kim_prototype import build_fixed_arm_housing_preview, build_weldment_tubes_preview


def _build_parts(document: dict[str, Any]) -> list[Any]:
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Iterator

    if document.get('format') == PREVIEW_FORMAT:
        validate_housing_preview(document)
        shape = build_fixed_arm_housing_preview(document)
        count = 4 if document['housings'] is not None else 2
    else:
        if not weldment_source_matches(document):
            raise ValueError('stale')
        shape = build_weldment_tubes_preview(document)
        count = 2
    iterator = TopoDS_Iterator(shape)
    parts = []
    while iterator.More():
        parts.append(iterator.Value())
        iterator.Next()
    if len(parts) != count or any(part.IsNull() or not BRepCheck_Analyzer(part).IsValid() for part in parts):
        raise ValueError('invalid_shape')
    return parts


def _volume(body: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(body, props, 1e-8)
    value = float(props.Mass())
    if not math.isfinite(value) or value < 0:
        raise ValueError('invalid_volume')
    return value


def _measure_pair(left: Any, right: Any, left_volume: float, right_volume: float) -> dict[str, float]:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepCheck import BRepCheck_Analyzer

    if min(left_volume, right_volume) <= 0:
        raise ValueError('invalid_volume')
    common = BRepAlgoAPI_Common(left, right)
    if not common.IsDone() or common.Shape().IsNull() or not BRepCheck_Analyzer(common.Shape()).IsValid():
        raise ValueError('intersection_failed')
    overlap = _volume(common.Shape())
    smaller = min(left_volume, right_volume)
    threshold = max(1e-6, smaller * 1e-9)
    if overlap > smaller + max(threshold, smaller * 1e-6):
        raise ValueError('invalid_volume')
    return {'overlap_mm3': overlap, 'threshold_mm3': threshold}


def measure_overlap(document: dict[str, Any]) -> dict[str, float]:
    """Объём общего материала двух труб, без расчёта расстояния/касания."""
    parts = _build_parts(document)
    return _measure_pair(parts[0], parts[1], _volume(parts[0]), _volume(parts[1]))


def measure_all_pairs(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Все пары двух труб и, при наличии, двух корпусов; без частичного результата."""
    parts = _build_parts(document)
    names = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')[:len(parts)]
    volumes = [_volume(part) for part in parts]
    if any(value <= 0 for value in volumes):
        raise ValueError('invalid_volume')
    result = []
    for left, right in combinations(range(len(parts)), 2):
        measured = _measure_pair(parts[left], parts[right], volumes[left], volumes[right])
        result.append({'left': names[left], 'right': names[right], **measured})
    return result


def _distance(left: Any, right: Any) -> tuple[float, list[list[float]], int]:
    """Расстояние и одна из пар ближайших точек на CAD-телах."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    calculation = BRepExtrema_DistShapeShape(left, right)
    if not calculation.IsDone() or calculation.NbSolution() < 1:
        raise ValueError('distance_failed')
    value = float(calculation.Value())
    if not math.isfinite(value) or value < 0 or value > 1e12:
        raise ValueError('distance_failed')
    points = []
    for p in (calculation.PointOnShape1(1), calculation.PointOnShape2(1)):
        coordinates = [float(p.X()), float(p.Y()), float(p.Z())]
        if any(not math.isfinite(v) or abs(v) > 1e10 for v in coordinates):
            raise ValueError('distance_failed')
        points.append(coordinates)
    return value, points, calculation.NbSolution()


def measure_proximity(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Дистанция и общий объём каждой пары после всех выбранных подрезок.

    Ошибка отдельной пары не выдаётся за нулевое расстояние и не скрывает другие пары.
    Ошибка построения исходных тел отклоняет весь отчёт.
    """
    from ..model.free_arm_io import FORMAT as FREE_ARM_FORMAT
    from .cad_fixed_arm_overlap_job import DISTANCE_TOLERANCE_MM

    if document.get('format') == FREE_ARM_FORMAT:
        from .cad_free_arm_overlap import build_independent_parts

        names, parts = build_independent_parts(document)
    else:
        parts = tuple(_build_parts(document))
        names = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')[:len(parts)]
    volumes = [_volume(part) for part in parts]
    if any(value <= 0 for value in volumes):
        raise ValueError('invalid_volume')
    result = []
    for left, right in combinations(range(len(parts)), 2):
        pair: dict[str, Any] = {'left': names[left], 'right': names[right]}
        try:
            measured = _measure_pair(parts[left], parts[right], volumes[left], volumes[right])
            distance, points, solutions = _distance(parts[left], parts[right])
            pair.update(measured, distance_mm=distance)
            if measured['overlap_mm3'] == 0 and distance > DISTANCE_TOLERANCE_MM:
                pair.update(points=points, solutions=solutions)
        except Exception:
            pair['error'] = 'measurement_failed'
        result.append(pair)
    return result


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (2, 3) or (len(args) == 3 and args[2] not in ('all', 'proximity', 'suggest', 'plan')):
        return 2
    source, target = map(Path, args[:2])
    try:
        data = json.loads(_read_project_bytes(source).decode('utf-8'), object_pairs_hook=_unique_object)
        payload: dict[str, Any]
        if len(args) == 2:
            payload = measure_overlap(data)
        elif args[2] == 'all':
            payload = {'pairs': measure_all_pairs(data)}
        elif args[2] == 'proximity':
            payload = {'pairs': measure_proximity(data)}
        elif args[2] == 'suggest':
            from .fixed_arm_suggestions import suggest
            payload = suggest(data)
        else:
            from .fixed_arm_plans import suggest_plan
            payload = suggest_plan(data)
        target.write_text(json.dumps({'status': 'ok', **payload}, allow_nan=False), encoding='utf-8')
        return 0
    except Exception:
        target.write_text(json.dumps({'status': 'error'}), encoding='utf-8')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
