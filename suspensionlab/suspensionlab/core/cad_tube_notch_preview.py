"""Вычисления предварительных CAD-видов пары труба — корпус до/после."""
from __future__ import annotations

from typing import Any

from .cad_assembly_projection import bounds_for_shape, project_shape
from .cad_kim_prototype import _place_scheme_arm_housing, build_part
from .cad_tube_notch import notch_tube_against_housing


def project_tube_notch(document: dict[str, Any], tube_id: str, housing_id: str) -> dict[str, Any]:
    """Изолированная пара неподрезанной и подрезанной трубы с тем же корпусом.

    Раздельные несоединённые тела: HLR при пересечениях может не отобразить
    все линии. При подрезке на месте отверстия остаётся свободное пространство;
    режущим телом является полный наружный цилиндр корпуса.
    """
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    result = notch_tube_against_housing(document, tube_id, housing_id)
    tube_index = ('tube_front', 'tube_rear').index(tube_id)
    housing_index = ('housing_front', 'housing_rear').index(housing_id)
    tube = build_part(document['parts'][tube_index])
    point = document['parts'][0]['geometry']['source']['coordinates_mm'][housing_index]
    housing = _place_scheme_arm_housing(document['parts'][housing_index + 2], point, document['axis'])
    builder = BRep_Builder()
    before, after = TopoDS_Compound(), TopoDS_Compound()
    builder.MakeCompound(before)
    builder.MakeCompound(after)
    builder.Add(before, tube)
    builder.Add(before, housing)
    builder.Add(after, result.shape)
    builder.Add(after, housing)
    # Same bounds for both states: each plane uses the same scale before/after.
    bounds = bounds_for_shape(before)
    return {'before': {'views': project_shape(before), 'bounds_mm': bounds},
            'after': {'views': project_shape(after), 'bounds_mm': bounds}}
