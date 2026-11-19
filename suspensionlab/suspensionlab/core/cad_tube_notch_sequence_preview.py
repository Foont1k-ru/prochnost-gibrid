"""CAD-проекции одной трубы до и после всей последовательности резов."""
from __future__ import annotations

from typing import Any

from .cad_assembly_projection import bounds_for_shape, project_shape
from .cad_kim_prototype import build_part
from .cad_tube_notch_sequence import TUBES, notch_tube_sequence


def project_notch_sequence(document: dict[str, Any], tube_id: str, cutter_ids: list[str]) -> dict[str, Any]:
    """Только исходная и итоговая труба; промежуточные результаты не возвращаются."""
    result = notch_tube_sequence(document, tube_id, cutter_ids)
    before = build_part(document['parts'][TUBES.index(tube_id)])
    bounds = bounds_for_shape(before)
    return {'before': {'views': project_shape(before), 'bounds_mm': bounds},
            'after': {'views': project_shape(result.shape), 'bounds_mm': bounds}}
