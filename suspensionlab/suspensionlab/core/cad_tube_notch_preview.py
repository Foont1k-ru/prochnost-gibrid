"""Вычисления предварительных CAD-видов выбранной пары до/после."""
from __future__ import annotations

from typing import Any

from .cad_assembly_projection import bounds_for_shape, project_shape
from .cad_kim_prototype import _place_scheme_arm_housing, _place_scheme_arm_plate, build_part
from .cad_tube_notch import notch_tube_against_housing, notch_tube_against_plate, notch_tube_against_tube


def project_tube_notch(document: dict[str, Any], tube_id: str, cutter_id: str) -> dict[str, Any]:
    """Изолированная пара до/после; HLR может не показать все пересечения.

    Корпус и труба режут наружным цилиндром; пластина — телом с отверстием.
    """
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    if cutter_id == 'ball_plate':
        result = notch_tube_against_plate(document, tube_id)
        cutting_part = _place_scheme_arm_plate(document)
    elif cutter_id in ('tube_front', 'tube_rear'):
        result = notch_tube_against_tube(document, tube_id, cutter_id)
        cutting_part = build_part(document['parts'][('tube_front', 'tube_rear').index(cutter_id)])
    else:
        result = notch_tube_against_housing(document, tube_id, cutter_id)
        housing_index = ('housing_front', 'housing_rear').index(cutter_id)
        point = document['parts'][0]['geometry']['source']['coordinates_mm'][housing_index]
        cutting_part = _place_scheme_arm_housing(document['parts'][housing_index + 2], point, document['axis'])
    tube_index = ('tube_front', 'tube_rear').index(tube_id)
    tube = build_part(document['parts'][tube_index])
    builder = BRep_Builder()
    before, after = TopoDS_Compound(), TopoDS_Compound()
    builder.MakeCompound(before)
    builder.MakeCompound(after)
    builder.Add(before, tube)
    builder.Add(before, cutting_part)
    builder.Add(after, result.shape)
    builder.Add(after, cutting_part)
    # Same bounds for both states: each plane uses the same scale before/after.
    bounds = bounds_for_shape(before)
    return {'before': {'views': project_shape(before), 'bounds_mm': bounds},
            'after': {'views': project_shape(after), 'bounds_mm': bounds}}
