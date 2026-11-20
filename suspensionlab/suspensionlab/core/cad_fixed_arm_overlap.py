"""Численное пересечение двух труб фиксированного снимка; не проверка зазоров."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from ..model.fixed_arm_housings import PREVIEW_FORMAT, validate_housing_preview
from ..model.project_io import _read_project_bytes, _unique_object
from ..model.welded_arm import weldment_source_matches
from .cad_kim_prototype import build_fixed_arm_housing_preview, build_weldment_tubes_preview


def measure_overlap(document: dict[str, Any]) -> dict[str, float]:
    """Объём общего материала двух построенных тел, без расчёта расстояния/касания."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS_Iterator

    if document.get('format') == PREVIEW_FORMAT:
        validate_housing_preview(document)
        shape = build_fixed_arm_housing_preview(document)
        count = 4
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
    if len(parts) != count or any(not BRepCheck_Analyzer(part).IsValid() for part in parts):
        raise ValueError('invalid_shape')

    def volume(body: Any) -> float:
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(body, props, 1e-8)
        value = float(props.Mass())
        if not math.isfinite(value) or value < 0:
            raise ValueError('invalid_volume')
        return value

    originals = [volume(part) for part in parts[:2]]
    if min(originals) <= 0:
        raise ValueError('invalid_volume')
    common = BRepAlgoAPI_Common(parts[0], parts[1])
    if not common.IsDone() or common.Shape().IsNull():
        raise ValueError('intersection_failed')
    overlap = volume(common.Shape())
    threshold = max(1e-6, min(originals) * 1e-9)
    if overlap > min(originals) + max(threshold, min(originals) * 1e-6):
        raise ValueError('invalid_volume')
    return {'overlap_mm3': overlap, 'threshold_mm3': threshold}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        return 2
    source, target = map(Path, args)
    try:
        data = json.loads(_read_project_bytes(source).decode('utf-8'), object_pairs_hook=_unique_object)
        result = measure_overlap(data)
        target.write_text(json.dumps({'status': 'ok', **result}, allow_nan=False), encoding='utf-8')
        return 0
    except Exception:
        target.write_text(json.dumps({'status': 'error'}), encoding='utf-8')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
