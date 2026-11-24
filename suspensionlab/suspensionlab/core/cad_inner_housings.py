"""Общее геометрическое ядро конечных корпусов внутренних опор."""
from __future__ import annotations

import math
from typing import Any


def build_inner_housings_and_notch(tubes: list[Any], centers: Any, housing_data: dict[str, Any],
                                    notches: dict[str, float]) -> tuple[list[Any], list[Any]]:
    """Выдать новые тела; при ошибке ни одна частичная сборка не возвращается."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    from .cad_kim_prototype import FixedArmNotchError
    from .cad_tube_notch import TubeNotchError, _cut_tube

    result = list(tubes)
    housings = []
    for index, leg in enumerate(('front', 'rear')):
        data = housing_data[leg]
        axis = data['axis']
        norm = math.hypot(*axis)
        direction = [v / norm for v in axis]
        length = float(data['length_mm'])
        origin = [float(centers[index][i]) - direction[i] * length / 2 for i in range(3)]
        frame = gp_Ax2(gp_Pnt(*origin), gp_Dir(*direction))
        outer = BRepPrimAPI_MakeCylinder(frame, float(data['outer_diameter_mm']) / 2, length).Shape()
        inner = BRepPrimAPI_MakeCylinder(frame, float(data['bore_diameter_mm']) / 2, length).Shape()
        cut = BRepAlgoAPI_Cut(outer, inner)
        if not cut.IsDone() or cut.Shape().IsNull() or not BRepCheck_Analyzer(cut.Shape()).IsValid():
            raise RuntimeError('invalid housing')
        housings.append(cut.Shape())
        if leg in notches:
            cutter = BRepPrimAPI_MakeCylinder(frame, float(data['outer_diameter_mm']) / 2 +
                                               float(notches[leg]), length).Shape()
            try:
                result[index] = _cut_tube(result[index], cutter, f'tube_{leg}', f'housing_{leg}').shape
            except TubeNotchError as error:
                raise FixedArmNotchError(leg, error.code) from error
    return result, housings
