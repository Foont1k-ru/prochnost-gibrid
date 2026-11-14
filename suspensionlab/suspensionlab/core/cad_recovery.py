"""Осторожное восстановление отдельных поверхностей только для просмотра.

Не исправляет STEP или B-rep и не доказывает корректность геометрии.
"""
from __future__ import annotations

import math


def recover_revolution_face(face, deviation: float):
    """Попытка восстановить полный колпак по профилю и единственной окружности.

    Возвращает новую грань только для узкого случая: поверхность вращения с
    конечным профилем от оси до единственной замкнутой окружности, без дыр.
    Восстановленная геометрия всегда помечается как предположение для просмотра.
    """
    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.Geom import Geom_SurfaceOfRevolution
        from OCP.GeomAbs import GeomAbs_CurveType
        from OCP.gp import gp_Lin, gp_Vec
        from OCP.TopAbs import TopAbs_ShapeEnum
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS

        surface = BRep_Tool.Surface_s(face)
        if not isinstance(surface, Geom_SurfaceOfRevolution):
            return None
        wires = TopExp_Explorer(face, TopAbs_ShapeEnum.TopAbs_WIRE)
        if not wires.More():
            return None
        wire = wires.Current()
        wires.Next()
        if wires.More():
            return None
        edges = TopExp_Explorer(wire, TopAbs_ShapeEnum.TopAbs_EDGE)
        if not edges.More():
            return None
        edge = TopoDS.Edge(edges.Current())
        edges.Next()
        if edges.More() or not BRep_Tool.IsClosed_s(edge):
            return None
        curve = BRepAdaptor_Curve(edge)
        if curve.GetType() != GeomAbs_CurveType.GeomAbs_Circle:
            return None
        circle = curve.Circle()
        u0, u1, v0, v1 = surface.Bounds()
        if (not all(math.isfinite(x) and abs(x) < 1e8 for x in (u0, u1, v0, v1)) or
                abs((u1 - u0) - 2 * math.pi) > 1e-8 or v1 <= v0):
            return None
        axis = surface.Axis()
        line = gp_Lin(axis)
        radius = circle.Radius()
        if not math.isfinite(radius) or not 1e-4 < radius < 1e6:
            return None
        # Малый допуск исключает явное несовпадение контура и исходного профиля.
        tolerance = max(1e-5, radius * 1e-6)
        if (not circle.Axis().Direction().IsParallel(axis.Direction(), 1e-6) or
                line.Distance(circle.Location()) > tolerance):
            return None
        profile = surface.BasisCurve()
        a, b = profile.Value(v0), profile.Value(v1)
        if line.Distance(a) <= tolerance and circle.Distance(b) <= tolerance:
            apex_first = True
        elif line.Distance(b) <= tolerance and circle.Distance(a) <= tolerance:
            apex_first = False
        else:
            return None
        # Исключаем профили, повторно пересекающие ось или складывающиеся по ней.
        origin, direction = axis.Location(), axis.Direction()
        samples = [profile.Value(v0 + (v1 - v0) * i / 16) for i in range(17)]
        axial = [gp_Vec(origin, p).Dot(gp_Vec(direction)) for p in samples]
        diffs = [axial[i + 1] - axial[i] for i in range(16)]
        if not (all(d >= -tolerance for d in diffs) or all(d <= tolerance for d in diffs)):
            return None
        if any(line.Distance(p) <= tolerance for p in samples[1:-1]):
            return None
        if line.Distance(b if apex_first else a) < radius - tolerance:
            return None
        maker = BRepBuilderAPI_MakeFace(surface, u0, u1, v0, v1, 1e-7)
        if not maker.IsDone():
            return None
        restored = maker.Face()
        mesher = BRepMesh_IncrementalMesh(restored, min(deviation, 1.), False, 0.4, False)
        location = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(restored, location)
        if not mesher.IsDone() or poly is None or poly.NbTriangles() <= 0:
            return None
        return restored
    except Exception:
        # Любая неоднозначность означает отказ, а не «исправление» произвольного STEP.
        return None
