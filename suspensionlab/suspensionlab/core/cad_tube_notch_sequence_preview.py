"""CAD-проекции исходной трубы и каждого шага завершённой последовательности."""
from __future__ import annotations

from typing import Any

from .cad_assembly_projection import bounds_for_shape, project_shape
from .cad_kim_prototype import build_part
from .cad_tube_notch_sequence import TUBES, notch_tube_sequence


def project_notch_sequence(document: dict[str, Any], tube_id: str, cutter_ids: list[str]) -> dict[str, Any]:
    """Только труба; все стадии передаются лишь после успеха всей цепочки."""
    result = notch_tube_sequence(document, tube_id, cutter_ids, capture_stages=True)
    before = build_part(document['parts'][TUBES.index(tube_id)])
    bounds = bounds_for_shape(before)
    stages = [{'cutter': step.cutter_id, 'projection': {'views': project_shape(shape), 'bounds_mm': bounds}}
              for step, shape in zip(result.steps, result.stage_shapes, strict=True)]
    return {'before': {'views': project_shape(before), 'bounds_mm': bounds}, 'stages': stages}
