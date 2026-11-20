"""Минимальный независимый CAD-прототип для проверки KIM, не модель подвески."""
from __future__ import annotations

from typing import Any

from ..model.kim_format import _assembly, _part


def _build_bent_tube(geometry: dict[str, Any], *, endpoints: tuple[Any, Any] | None = None,
                     solid_envelope: bool = False, radial_clearance_mm: float = 0.) -> Any:
    """Полая труба или сплошной наружный объём вдоль прямых и касательной дуги."""
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
    outer = float(geometry["radius_mm"]) + radial_clearance_mm
    path = make_bend_path(endpoints[0], geometry["bend_vertex_mm"], endpoints[1],
                          geometry["bend_radius_mm"], outer)
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
    def circle(radius: float) -> Any:
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(axis, radius)).Edge()).Wire()
    face = BRepBuilderAPI_MakeFace(circle(outer), True)
    if not solid_envelope:
        inner = outer - float(geometry["wall_mm"])
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
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    geometry = document["geometry"]
    if geometry["kind"] == "prototype_rectangular_plate_hole":
        width, height, thickness = (float(geometry[key]) for key in ("width_mm", "height_mm", "thickness_mm"))
        box = BRepPrimAPI_MakeBox(gp_Pnt(-width / 2, -height / 2, -thickness / 2), width, height, thickness).Shape()
        hole_axis = gp_Ax2(gp_Pnt(0, 0, -thickness / 2), gp_Dir(0, 0, 1))
        hole = BRepPrimAPI_MakeCylinder(hole_axis, float(geometry["hole_radius_mm"]), thickness).Shape()
        cut = BRepAlgoAPI_Cut(box, hole)
        if not cut.IsDone() or cut.Shape().IsNull():
            raise RuntimeError("could not build plate")
        return cut.Shape()
    if geometry["kind"] == "prototype_bushing_housing":
        length = float(geometry["length_mm"])
        axis = gp_Ax2(gp_Pnt(0, 0, -length / 2), gp_Dir(0, 0, 1))
        outside = BRepPrimAPI_MakeCylinder(axis, float(geometry["outer_radius_mm"]), length).Shape()
        bore = BRepPrimAPI_MakeCylinder(axis, float(geometry["bore_radius_mm"]), length).Shape()
        cut = BRepAlgoAPI_Cut(outside, bore)
        if not cut.IsDone() or cut.Shape().IsNull():
            raise RuntimeError("could not build housing part")
        return cut.Shape()
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
    if document.get("version") == "0.4" and document.get("format") == "kim-part":
        # Independent hollow housing solids, centred on the two inner pivots.
        data = document["bushings"]
        bush_dir = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[data["axis"]]
        length = float(data["length_mm"])
        for point in points[:2]:
            origin = [float(point[i]) - length * bush_dir[i] / 2 for i in range(3)]
            axis = gp_Ax2(gp_Pnt(*origin), gp_Dir(*bush_dir))
            outside = BRepPrimAPI_MakeCylinder(axis, float(data["outer_radius_mm"]), length).Shape()
            bore = BRepPrimAPI_MakeCylinder(axis, float(data["bore_radius_mm"]), length).Shape()
            cut = BRepAlgoAPI_Cut(outside, bore)
            if not cut.IsDone() or cut.Shape().IsNull():
                raise RuntimeError("could not build bushing housing")
            builder.Add(compound, cut.Shape())
    return compound


def build_assembly(document: dict[str, Any]) -> Any:
    """Создаёт соединение перенесённых экземпляров, не связывая их со схемой."""
    _assembly(document)
    if document["version"] in ("0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "0.10", "0.11", "0.12", "0.13", "0.14", "0.15", "0.16"):
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


def _fixed_arm_tube_envelope(part: dict[str, Any], clearance: float) -> Any:
    """Сплошной наружный объём исходной трубы, без продления её осевой линии."""
    import math

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    geometry = part['geometry']
    if geometry['kind'] == 'prototype_arm_bent_tube':
        return _build_bent_tube(geometry, solid_envelope=True, radial_clearance_mm=clearance)
    if geometry['kind'] != 'prototype_arm_tube':
        raise ValueError('unsupported tube')
    points = geometry['source']['coordinates_mm']
    start, end = points[0 if geometry['leg'] == 'front' else 1], points[2]
    direction = [float(end[i]) - float(start[i]) for i in range(3)]
    frame = gp_Ax2(gp_Pnt(*map(float, start)), gp_Dir(*direction))
    return BRepPrimAPI_MakeCylinder(frame, float(geometry['radius_mm']) + clearance,
                                     math.dist(start, end)).Shape()


class FixedArmNotchError(ValueError):
    """Отклонённая подрезка одной ветви; никакая частичная сборка не выдаётся."""

    def __init__(self, leg: str, code: str, *, tube_joint: bool = False) -> None:
        super().__init__(code)
        self.leg = leg
        self.code = code
        self.tube_joint = tube_joint


def build_fixed_arm_housing_preview(document: dict[str, Any]) -> Any:
    """Две трубы, опциональные корпуса и явно выбранные неподвижные резы."""
    import math

    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    from ..model.fixed_arm_housings import validate_housing_preview

    validate_housing_preview(document)
    tube_doc = document['tubes']
    points = tube_doc['parts'][0]['geometry']['source']['coordinates_mm']
    from .cad_tube_notch import TubeNotchError, _cut_tube

    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    tubes = [build_part(part) for part in tube_doc['parts']]
    housings = []
    notches = document.get('notches') or {}
    housing_data = document['housings']
    for index, leg in enumerate(('front', 'rear')) if housing_data is not None else ():
        data = housing_data[leg]
        axis = data['axis']
        norm = math.hypot(*axis)
        direction = [v / norm for v in axis]
        length = float(data['length_mm'])
        origin = [float(points[index][i]) - direction[i] * length / 2 for i in range(3)]
        frame = gp_Ax2(gp_Pnt(*origin), gp_Dir(*direction))
        outer = BRepPrimAPI_MakeCylinder(frame, float(data['outer_diameter_mm']) / 2, length).Shape()
        inner = BRepPrimAPI_MakeCylinder(frame, float(data['bore_diameter_mm']) / 2, length).Shape()
        cut = BRepAlgoAPI_Cut(outer, inner)
        if not cut.IsDone() or cut.Shape().IsNull() or not BRepCheck_Analyzer(cut.Shape()).IsValid():
            raise RuntimeError('invalid housing')
        housings.append(cut.Shape())
        if leg in notches:
            # Solid outside envelope, not the housing's annular material. The
            # finite length and requested radial clearance are never extended.
            cutter = BRepPrimAPI_MakeCylinder(frame, float(data['outer_diameter_mm']) / 2 +
                                               float(notches[leg]), length).Shape()
            try:
                result = _cut_tube(tubes[index], cutter, f'tube_{leg}', f'housing_{leg}')
            except TubeNotchError as error:
                raise FixedArmNotchError(leg, error.code) from error
            tubes[index] = result.shape
    if document.get('tube_joint') is not None:
        joint = document['tube_joint']
        leg = joint['target']
        target_index = ('front', 'rear').index(leg)
        other_index = 1 - target_index
        try:
            # The cutter always uses the ORIGINAL opposite tube, not its
            # optionally housing-notched result. No guessed extension or weld.
            cutter = _fixed_arm_tube_envelope(tube_doc['parts'][other_index], joint['radial_clearance_mm'])
            result = _cut_tube(tubes[target_index], cutter, f'tube_{leg}',
                               f'tube_{("front", "rear")[other_index]}')
        except TubeNotchError as error:
            raise FixedArmNotchError(leg, error.code, tube_joint=True) from error
        except Exception as error:
            raise FixedArmNotchError(leg, 'failed', tube_joint=True) from error
        tubes[target_index] = result.shape
    for shape in (*tubes, *housings):
        if shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
            raise RuntimeError('invalid part')
        builder.Add(compound, shape)
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

    from ..model.front_joint_layout import front_bushing_axis, validate_front_joint_layout
    from ..model.front_pair_snapshot import front_pair_sides
    from ..model.front_same_pair import front_same_pair_sides
    from ..model.front_tube_arm import front_tube_arm_points

    validate_front_joint_layout(document)
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, build_front_pair_preview(document['pair']))
    ball, bushing = build_joint_preview(document['ball']), build_joint_preview(document['bushing'])
    # Joints are independent conditional placeholders, not transformed attachments.
    sides = (front_same_pair_sides(document['pair']) if document['pair']['version'] == '0.11'
             else front_pair_sides(document['pair']))
    axis = front_bushing_axis(document)
    for arm in sides:
        points = front_tube_arm_points(arm)
        for index, point in enumerate(points):
            transform = gp_Trsf()
            if index < 2 and axis == 'x':
                # Local joint +Z -> vehicle +X (longitudinal).
                transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)), math.pi/2)
            elif index < 2 and axis == 'y':
                # Old formats retain +Y, transverse to the vehicle.
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


def _place_scheme_arm_housing(part: dict[str, Any], point: Any, axis: str) -> Any:
    """Разместить валидированный корпус в системе снимка сборки."""
    import math

    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

    transform = gp_Trsf()
    if axis == 'x':
        transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)), math.pi / 2)
    elif axis == 'y':
        transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), -math.pi / 2)
    transform.SetTranslationPart(gp_Vec(*point))
    placed = BRepBuilderAPI_Transform(build_part(part), transform, True).Shape()
    if placed.IsNull():
        raise RuntimeError('housing placement failed')
    return placed


def _place_scheme_arm_plate(document: dict[str, Any]) -> Any:
    """Разместить валидированную пластину по снимку, с её отверстием."""
    import math

    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

    points = document['parts'][0]['geometry']['source']['coordinates_mm']
    placement = document['plate_placement']
    transform = gp_Trsf()
    if placement['normal'] == 'x':
        transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)), math.pi / 2)
    elif placement['normal'] == 'y':
        transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), -math.pi / 2)
    position = [float(points[2][i]) + float(placement['offset_mm'][i]) for i in range(3)]
    transform.SetTranslationPart(gp_Vec(*position))
    plate = BRepBuilderAPI_Transform(build_part(document['parts'][4]), transform, True).Shape()
    if plate.IsNull():
        raise RuntimeError('plate placement failed')
    return plate


def build_scheme_arm_assembly_preview(document: dict[str, Any]) -> Any:
    """Две встроенные трубы и размещённые детали без объединения."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    from ..model.scheme_arm_assembly import validate_scheme_arm_assembly

    validate_scheme_arm_assembly(document)
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for part in document['parts'][:2]:
        builder.Add(compound, build_part(part))
    points = document['parts'][0]['geometry']['source']['coordinates_mm']
    for part, point in zip(document['parts'][2:4], points[:2], strict=True):
        builder.Add(compound, _place_scheme_arm_housing(part, point, document['axis']))
    if document['version'] == '0.16':
        builder.Add(compound, _place_scheme_arm_plate(document))
    return compound
