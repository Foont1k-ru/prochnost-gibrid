"""Вычисления предварительных CAD-видов выбранной пары до/после."""
from __future__ import annotations

from typing import Any

from .cad_assembly_projection import bounds_for_shape, project_shape
from .cad_kim_prototype import _place_scheme_arm_housing, _place_scheme_arm_plate, build_part
from .cad_tube_notch import notch_tube_against_housing, notch_tube_against_plate, notch_tube_against_tube


def display_cutting_part(document: dict[str, Any], cutter_id: str) -> Any:
    """Реальная размещённая деталь для вида, не обязательно её режущий объём.

    Документ и выбор должны быть заранее проверены. Корпус и режущая труба
    показаны полыми, хотя при вычитании используется сплошной наружный цилиндр.
    """
    if cutter_id == 'ball_plate':
        return _place_scheme_arm_plate(document)
    if cutter_id in ('tube_front', 'tube_rear'):
        return build_part(document['parts'][('tube_front', 'tube_rear').index(cutter_id)])
    if cutter_id in ('housing_front', 'housing_rear'):
        index = ('housing_front', 'housing_rear').index(cutter_id)
        point = document['parts'][0]['geometry']['source']['coordinates_mm'][index]
        return _place_scheme_arm_housing(document['parts'][index + 2], point, document['axis'])
    raise ValueError('unsupported cutting part')


def project_tube_notch(document: dict[str, Any], tube_id: str, cutter_id: str) -> dict[str, Any]:
    """Изолированная пара до/после; HLR может не показать все пересечения.

    Корпус и труба режут наружным цилиндром; пластина — телом с отверстием.
    """
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    if cutter_id == 'ball_plate':
        result = notch_tube_against_plate(document, tube_id)
    elif cutter_id in ('tube_front', 'tube_rear'):
        result = notch_tube_against_tube(document, tube_id, cutter_id)
    else:
        result = notch_tube_against_housing(document, tube_id, cutter_id)
    cutting_part = display_cutting_part(document, cutter_id)
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
    # In each mode both states use the original bounds and identical scale.
    # Tube-only views reveal contours otherwise obscured by the cutting part.
    pair_bounds = bounds_for_shape(before)
    tube_bounds = bounds_for_shape(tube)
    return {'before': {'views': project_shape(before), 'bounds_mm': pair_bounds},
            'after': {'views': project_shape(after), 'bounds_mm': pair_bounds},
            'tube_before': {'views': project_shape(tube), 'bounds_mm': tube_bounds},
            'tube_after': {'views': project_shape(result.shape), 'bounds_mm': tube_bounds}}
