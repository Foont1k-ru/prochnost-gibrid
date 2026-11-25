"""CAD-проекции исходной трубы и каждого шага завершённой последовательности."""
from __future__ import annotations

from typing import Any

from .cad_assembly_projection import bounds_for_shape, project_shape
from .cad_kim_prototype import build_part
from .cad_tube_notch_preview import display_cutting_part
from .cad_tube_notch_sequence import MAX_SEQUENCE_SEGMENTS, TUBES, notch_tube_sequence
from .cad_worker import CadWorkerError


def project_notch_sequence(document: dict[str, Any], tube_id: str, cutter_ids: list[str]) -> dict[str, Any]:
    """Исходная труба, этапы и пары до/после каждого реза; только при общем успехе."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    result = notch_tube_sequence(document, tube_id, cutter_ids, capture_stages=True)
    before = build_part(document['parts'][TUBES.index(tube_id)])
    bounds = bounds_for_shape(before)
    total_segments = 0

    def project(shape: Any, shape_bounds: list[float]) -> dict[str, Any]:
        nonlocal total_segments
        views = project_shape(shape)
        total_segments += sum(len(lines) for lines in views.values())
        if total_segments > MAX_SEQUENCE_SEGMENTS:
            raise CadWorkerError('limit')
        return {'views': views, 'bounds_mm': shape_bounds}

    before_projection = project(before, bounds)
    stages = []
    previous = before
    for step, shape in zip(result.steps, result.stage_shapes, strict=True):
        cutter = display_cutting_part(document, step.cutter_id)
        builder = BRep_Builder()
        pair_before, pair_after = TopoDS_Compound(), TopoDS_Compound()
        builder.MakeCompound(pair_before)
        builder.MakeCompound(pair_after)
        builder.Add(pair_before, previous)
        builder.Add(pair_before, cutter)
        builder.Add(pair_after, shape)
        builder.Add(pair_after, cutter)
        pair_bounds = bounds_for_shape(pair_before)
        stages.append({'cutter': step.cutter_id, 'projection': project(shape, bounds),
                       'pair_before': project(pair_before, pair_bounds),
                       'pair_after': project(pair_after, pair_bounds),
                       'input_volume_mm3': step.input_volume_mm3,
                       'remaining_volume_mm3': step.remaining_volume_mm3,
                       'removed_volume_mm3': step.removed_volume_mm3})
        previous = shape
    return {'before': before_projection, 'stages': stages}
