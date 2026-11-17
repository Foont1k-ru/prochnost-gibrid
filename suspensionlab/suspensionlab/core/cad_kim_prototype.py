"""Минимальный независимый CAD-прототип для проверки KIM, не модель подвески."""
from __future__ import annotations

from typing import Any

from ..model.kim_format import _assembly, _part


def _build_bent_tube(geometry: dict[str, Any], *, endpoints: tuple[Any, Any] | None = None) -> Any:
    """Круглое полое сечение вдоль двух прямых и касательной дуги."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS

    from ..model.bent_tube import make_bend_path

    if endpoints is None:
        points = geometry["source"]["coordinates_mm"]
        endpoints = (points[0 if geometry["leg"] == "front" else 1], points[2])
    path = make_bend_path(endpoints[0], geometry["bend_vertex_mm"], endpoints[1],
                          geometry["bend_radius_mm"], geometry["radius_mm"])
    start, t1, middle, t2, end = (gp_Pnt(*p) for p in
                                   (path.start, path.tangent_start, path.midpoint, path.tangent_end, path.end))
    arc = GC_MakeArcOfCircle(t1, middle, t2)
    if not arc.IsDone():
        raise RuntimeError("could not construct bend arc")
    wire = BRepBuilderAPI_MakeWire()
    wire.Add(BRepBuilderAPI_MakeEdge(start, t1).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(arc.Value()).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(t2, end).Edge())
    if not wire.IsDone():
        raise RuntimeError("could not construct bend path")
    direction = [path.tangent_start[i] - path.start[i] for i in range(3)]
    axis = gp_Ax2(start, gp_Dir(*direction))
    outer = float(geometry["radius_mm"])
    inner = outer - float(geometry["wall_mm"])
    def circle(radius: float) -> Any:
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(axis, radius)).Edge()).Wire()
    face = BRepBuilderAPI_MakeFace(circle(outer), True)
    face.Add(TopoDS.Wire(circle(inner).Reversed()))
    if not face.IsDone():
        raise RuntimeError("could not construct hollow section")
    sweep = BRepOffsetAPI_MakePipe(wire.Wire(), face.Face())
    if not sweep.IsDone() or sweep.Shape().IsNull() or not BRepCheck_Analyzer(sweep.Shape()).IsValid():
        raise RuntimeError("could not build bent tube")
    return sweep.Shape()


def build_part(document: dict[str, Any]) -> Any:
    """Перестраивает только экспериментальную геометрию, не реальную деталь."""
    _part(document)
    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    geometry = document["geometry"]
    if geometry["kind"] == "prototype_arm_bent_tube":
        return _build_bent_tube(geometry)
    if geometry["kind"] == "prototype_cylinder":
        return BRepPrimAPI_MakeCylinder(float(geometry["radius_mm"]), float(geometry["length_mm"])).Shape()
    import math

    points = geometry["source"]["coordinates_mm"]
    outer = points[2]
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    legs = points[:2]
    if geometry["kind"] == "prototype_arm_tube":
        legs = [points[0 if geometry["leg"] == "front" else 1]]
    for inner in legs:
        direction = [float(b) - float(a) for a, b in zip(inner, outer, strict=True)]
        axis = gp_Ax2(gp_Pnt(*map(float, inner)), gp_Dir(*direction))
        length = math.dist(inner, outer)
        radius = float(geometry["radius_mm"])
        rod = BRepPrimAPI_MakeCylinder(axis, radius, length).Shape()
        if geometry["kind"] in ("prototype_lower_arm_tubes", "prototype_arm_tube"):
            bore = BRepPrimAPI_MakeCylinder(axis, radius - float(geometry["wall_mm"]), length).Shape()
            cut = BRepAlgoAPI_Cut(rod, bore)
            if not cut.IsDone() or cut.Shape().IsNull():
                raise RuntimeError("could not build prototype tube")
            rod = cut.Shape()
        builder.Add(compound, rod)
    return compound


def build_assembly(document: dict[str, Any]) -> Any:
    """Создаёт соединение перенесённых экземпляров, не связывая их со схемой."""
    _assembly(document)
    if document["version"] in ("0.2", "0.3", "0.4", "0.5", "0.6"):
        raise ValueError("incomplete weldment: use the explicitly partial tube preview")
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.TopoDS import TopoDS_Compound

    parts = {part["id"]: build_part(part) for part in document["parts"]}
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for instance in document["instances"]:
        x, y, z = instance["translation_mm"]
        transform = gp_Trsf()
        transform.SetTranslation(gp_Vec(float(x), float(y), float(z)))
        builder.Add(compound, BRepBuilderAPI_Transform(parts[instance["part_id"]], transform, True).Shape())
    return compound


def build_weldment_tubes_preview(document: dict[str, Any]) -> Any:
    """Только неполные трубы: кронштейнов, втулок, сварки и изделий нет."""
    from ..model.welded_arm import weldment_source_matches

    if not weldment_source_matches(document):
        raise ValueError("assembly source differs from saved scheme")
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for part in document["parts"]:
        builder.Add(compound, build_part(part))
    return compound


def build_rear_tube_preview(document: dict[str, Any]) -> Any:
    """Одна полая труба, без втулок, креплений и сварки."""
    import math

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    from ..model.rear_tube import rear_tube_points

    start, end = rear_tube_points(document)
    radius, wall = float(document['radius_mm']), float(document['wall_mm'])
    if document['bend'] is not None:
        bend = document['bend']
        return _build_bent_tube({'radius_mm': radius, 'wall_mm': wall,
                                 'bend_vertex_mm': bend['vertex_mm'], 'bend_radius_mm': bend['radius_mm']},
                                endpoints=(start, end))
    axis = gp_Ax2(gp_Pnt(*start), gp_Dir(*(end[i] - start[i] for i in range(3))))
    length = math.dist(start, end)
    outer = BRepPrimAPI_MakeCylinder(axis, radius, length).Shape()
    bore = BRepPrimAPI_MakeCylinder(axis, radius - wall, length).Shape()
    cut = BRepAlgoAPI_Cut(outer, bore)
    if not cut.IsDone() or cut.Shape().IsNull() or not BRepCheck_Analyzer(cut.Shape()).IsValid():
        raise RuntimeError('could not build rear tube')
    return cut.Shape()


def build_front_arm_tubes_preview(document: dict[str, Any]) -> Any:
    """Только две неподрезанные полые трубы; крепления и сварка отсутствуют."""
    import math

    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    from ..model.front_tube_arm import LEGS, front_tube_arm_points

    points = front_tube_arm_points(document)
    radius, wall = float(document['radius_mm']), float(document['wall_mm'])
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for index, leg in enumerate(LEGS):
        start, end = points[index], points[2]
        bend = document['bends'].get(leg)
        if bend is not None:
            shape = _build_bent_tube({'radius_mm': radius, 'wall_mm': wall,
                                      'bend_vertex_mm': bend['vertex_mm'], 'bend_radius_mm': bend['radius_mm']},
                                     endpoints=(start, end))
        else:
            axis = gp_Ax2(gp_Pnt(*start), gp_Dir(*(end[i] - start[i] for i in range(3))))
            length = math.dist(start, end)
            cut = BRepAlgoAPI_Cut(BRepPrimAPI_MakeCylinder(axis, radius, length).Shape(),
                                  BRepPrimAPI_MakeCylinder(axis, radius - wall, length).Shape())
            if not cut.IsDone() or cut.Shape().IsNull() or not BRepCheck_Analyzer(cut.Shape()).IsValid():
                raise RuntimeError('could not build front tube')
            shape = cut.Shape()
        builder.Add(compound, shape)
    return compound


def build_rear_pair_preview(document: dict[str, Any]) -> Any:
    """Две трубы в системе задней оси, без соединений и установки шарниров."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    from ..model.rear_pair_snapshot import rear_pair_sides

    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for tube in rear_pair_sides(document):
        builder.Add(compound, build_rear_tube_preview(tube))
    return compound
