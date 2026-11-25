"""Конечный наружный объём исходной прямой или изогнутой трубы."""
from __future__ import annotations

import math
from typing import Any


def build_tube_envelope(geometry: dict[str, Any], start: Any, end: Any, clearance: float) -> Any:
    """Сплошной резец с радиальным зазором, без продления осевой линии."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    from .cad_kim_prototype import _build_bent_tube

    if geometry['kind'] == 'prototype_arm_bent_tube':
        return _build_bent_tube(geometry, endpoints=(start, end), solid_envelope=True,
                                radial_clearance_mm=clearance)
    if geometry['kind'] != 'prototype_arm_tube':
        raise ValueError('unsupported tube')
    direction = [float(end[i]) - float(start[i]) for i in range(3)]
    frame = gp_Ax2(gp_Pnt(*map(float, start)), gp_Dir(*direction))
    return BRepPrimAPI_MakeCylinder(frame, float(geometry['radius_mm']) + clearance,
                                     math.dist(start, end)).Shape()
