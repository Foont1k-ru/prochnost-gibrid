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
    if document["version"] in ("0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "0.10", "0.11"):
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


def build_front_pair_preview(document: dict[str, Any]) -> Any:
    """Четыре неподрезанные трубы двух зеркальных передних рычагов."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    from ..model.front_pair_snapshot import front_pair_sides
    from ..model.front_same_pair import front_same_pair_sides

    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    sides = front_same_pair_sides(document) if document.get('version') == '0.11' else front_pair_sides(document)
    for arm in sides:
        builder.Add(compound, build_front_arm_tubes_preview(arm))
    return compound


def build_joint_preview(document: dict[str, Any]) -> Any:
    """Условный корпус и палец: отдельные твёрдые тела, локальная ось +Z."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    from ..model.joint_concept import validate_joint_concept

    validate_joint_concept(document)
    p = document['parameters']
    def cylinder(radius: float, z: float, length: float) -> Any:
        return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)), radius, length).Shape()
    def cut(first: Any, second: Any) -> Any:
        operation = BRepAlgoAPI_Cut(first, second)
        if not operation.IsDone() or operation.Shape().IsNull():
            raise RuntimeError('joint cut failed')
        return operation.Shape()
    if document['joint_type'] == 'ball':
        shell = cut(BRepPrimAPI_MakeSphere(float(p['outer_radius_mm'])).Shape(),
                    BRepPrimAPI_MakeSphere(float(p['cavity_radius_mm'])).Shape())
        body = cut(shell, cylinder(float(p['opening_radius_mm']), 0, float(p['outer_radius_mm']) + 1))
        ball = BRepPrimAPI_MakeSphere(float(p['ball_radius_mm'])).Shape()
        fusion = BRepAlgoAPI_Fuse(ball, cylinder(float(p['pin_radius_mm']), 0, float(p['pin_length_mm'])))
        if not fusion.IsDone() or fusion.Shape().IsNull():
            raise RuntimeError('joint pin fusion failed')
        pin = fusion.Shape()
    else:
        length = float(p['body_length_mm'])
        body = cut(cylinder(float(p['outer_radius_mm']), -length / 2, length),
                   cylinder(float(p['bore_radius_mm']), -length / 2, length))
        length = float(p['pin_length_mm'])
        pin = cylinder(float(p['pin_radius_mm']), -length / 2, length)
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for part in (body, pin):
        if not BRepCheck_Analyzer(part).IsValid():
            raise RuntimeError('invalid joint geometry')
        builder.Add(compound, part)
    return compound


def build_front_joint_layout_preview(document: dict[str, Any]) -> Any:
    """Компоновка: 4 трубы и 6 условных корпусов с пальцами, без соединений."""
    import math

    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopoDS import TopoDS_Compound

    from ..model.front_joint_layout import validate_front_joint_layout
    from ..model.front_pair_snapshot import front_pair_sides
    from ..model.front_tube_arm import front_tube_arm_points

    validate_front_joint_layout(document)
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, build_front_pair_preview(document['pair']))
    ball, bushing = build_joint_preview(document['ball']), build_joint_preview(document['bushing'])
    for arm in front_pair_sides(document['pair']):
        points = front_tube_arm_points(arm)
        for index, point in enumerate(points):
            transform = gp_Trsf()
            if index < 2:
                # Local joint +Z -> vehicle +Y. Bushing is axially symmetric.
                transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), -math.pi/2)
            transform.SetTranslationPart(gp_Vec(*point))
            shape = bushing if index < 2 else ball
            placed = BRepBuilderAPI_Transform(shape, transform, True).Shape()
            if placed.IsNull():
                raise RuntimeError('joint placement failed')
            builder.Add(compound, placed)
    return compound


def build_rear_joint_layout_preview(document: dict[str, Any]) -> Any:
    """Две трубы и четыре условные втулки без сварки и проверки монтажа."""
    import math

    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopoDS import TopoDS_Compound

    from ..model.rear_joint_layout import validate_rear_joint_layout
    from ..model.rear_pair_snapshot import rear_pair_sides
    from ..model.rear_tube import rear_tube_points

    validate_rear_joint_layout(document)
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, build_rear_pair_preview(document['pair']))
    bushing = build_joint_preview(document['bushing'])
    for tube in rear_pair_sides(document['pair']):
        for point in rear_tube_points(tube):
            transform = gp_Trsf()
            if document['axis'] == 'x':
                transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)), math.pi / 2)
            elif document['axis'] == 'y':
                transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), -math.pi / 2)
            transform.SetTranslationPart(gp_Vec(*point))
            placed = BRepBuilderAPI_Transform(bushing, transform, True).Shape()
            if placed.IsNull():
                raise RuntimeError('joint placement failed')
            builder.Add(compound, placed)
    return compound
