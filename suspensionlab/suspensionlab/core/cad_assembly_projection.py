"""Прототип видимых линий CAD-сборки, вычисляемый только в CAD-процессе."""
from __future__ import annotations

import math
from typing import Any

from .cad_worker import CadWorkerError

PLANES = ('XY', 'XZ', 'YZ')
MAX_SEGMENTS = 30000
MAX_COORDINATE = 2_000_000.
DEFLECTION_MM = 0.25  # аппроксимация кривых для экрана, не производственный допуск


def project_shape(shape: Any) -> dict[str, list[list[float]]]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    # normal and horizontal axis; vertical = normal cross horizontal, all in
    # the vehicle coordinate system. Each result is already in projector XY.
    cameras = {'XY': ((0, 0, 1), (1, 0, 0)), 'XZ': ((0, -1, 0), (1, 0, 0)),
               'YZ': ((1, 0, 0), (0, 1, 0))}
    result: dict[str, list[list[float]]] = {}
    total = 0
    for plane, (normal, right) in cameras.items():
        algo = HLRBRep_Algo()
        algo.Add(shape)
        algo.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*normal), gp_Dir(*right))))
        algo.Update()
        algo.Hide()
        converter = HLRBRep_HLRToShape(algo)
        segments: list[list[float]] = []
        for compound in (converter.VCompound(), converter.OutLineVCompound()):
            if compound.IsNull():
                continue
            explorer = TopExp_Explorer(compound, TopAbs_EDGE)
            while explorer.More():
                curve = BRepAdaptor_Curve(TopoDS.Edge(explorer.Current()))
                if not math.isfinite(curve.FirstParameter()) or not math.isfinite(curve.LastParameter()):
                    raise CadWorkerError('coordinates')
                sampler = GCPnts_QuasiUniformDeflection(curve, DEFLECTION_MM)
                if not sampler.IsDone() or sampler.NbPoints() < 2:
                    raise CadWorkerError('projection')
                count = sampler.NbPoints() - 1
                total += count
                if total > MAX_SEGMENTS:
                    raise CadWorkerError('limit')
                prior = sampler.Value(1)
                for i in range(2, sampler.NbPoints() + 1):
                    point = sampler.Value(i)
                    line = [prior.X(), prior.Y(), point.X(), point.Y()]
                    if not all(math.isfinite(x) and abs(x) <= MAX_COORDINATE for x in line):
                        raise CadWorkerError('coordinates')
                    segments.append(line)
                    prior = point
                explorer.Next()
        if not segments:
            raise CadWorkerError('projection')
        result[plane] = segments
    return result


def bounds_for_shape(shape: Any) -> list[float]:
    """Границы всех CAD-тел в координатах кузова, включая скрытые тела."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, bounds, False, False)
    if bounds.IsVoid() or bounds.IsOpen():
        raise CadWorkerError('coordinates')
    low, high = bounds.CornerMin(), bounds.CornerMax()
    coordinates = [low.X(), low.Y(), low.Z(), high.X(), high.Y(), high.Z()]
    if (not all(math.isfinite(x) and abs(x) <= MAX_COORDINATE for x in coordinates) or
            any(coordinates[i] >= coordinates[i + 3] for i in range(3))):
        raise CadWorkerError('coordinates')
    return coordinates


def project_document(document: dict[str, Any]) -> dict[str, Any]:
    from OCP.BRepCheck import BRepCheck_Analyzer

    from ..model.scheme_arm_assembly import validate_scheme_arm_assembly
    from .cad_kim_prototype import build_scheme_arm_assembly_preview

    validate_scheme_arm_assembly(document)
    shape = build_scheme_arm_assembly_preview(document)
    if shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
        raise CadWorkerError('no_shape')
    return {'views': project_shape(shape), 'bounds_mm': bounds_for_shape(shape)}
