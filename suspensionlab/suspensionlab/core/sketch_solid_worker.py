"""Изолированный OCCT worker: аналитические контуры -> STEP-тело в мм."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from ..model.sketch_contours import check_contours
from ..model.sketch_curves import NUMERIC_EPS_MM, distance, endpoints, point_at
from ..model.sketch_draft import Entity, Point
from ..model.sketch_extrude_settings import extrusion_limits, hole_entry_side, validate_hole_depth
from ..model.sketch_io import SketchDocument, read_sketch


class ContourLayoutError(ValueError):
    """Отдельные внешние контуры или вложенные острова не поддерживаются."""


def ordered_contour(entities: tuple[Entity, ...]) -> tuple[tuple[Entity, bool], ...]:
    """Совместимый помощник для единственного контура."""
    contours = ordered_contours(entities)
    if len(contours) != 1:
        raise ValueError("Нужен один замкнутый контур")
    return contours[0]


def ordered_contours(entities: tuple[Entity, ...]) -> tuple[tuple[tuple[Entity, bool], ...], ...]:
    """Разделяет проверенные замкнутые компоненты; вложенность проверяет CAD-ядро."""
    report = check_contours(entities)
    if report.total_issues or not report.closed_loops:
        raise ValueError("Нужны замкнутые контуры без разрывов, пересечений и касаний")
    remaining = set(range(len(entities)))
    result: list[tuple[tuple[Entity, bool], ...]] = []
    while remaining:
        first = min(remaining)
        if entities[first].kind == "circle":
            remaining.remove(first)
            result.append(((entities[first], False),))
            continue
        start = endpoints(entities[first])[0]
        current = start
        ordered: list[tuple[Entity, bool]] = []
        while True:
            matches = ([(first, 0)] if not ordered else
                       [(i, side) for i in sorted(remaining) for side, p in enumerate(endpoints(entities[i]))
                        if distance(current, p) <= NUMERIC_EPS_MM])
            if len(matches) != 1:
                raise ValueError("Не удалось однозначно упорядочить контур")
            index, side = matches[0]
            remaining.remove(index)
            entity = entities[index]
            ordered.append((entity, side == 1))
            current = endpoints(entity)[1 - side]
            if distance(current, start) <= NUMERIC_EPS_MM:
                break
        result.append(tuple(ordered))
    if len(result) != report.closed_loops:
        raise ValueError("Не удалось разделить контуры")
    return tuple(result)


def build_solid(document: SketchDocument, depth: float, direction: str = "positive", hole_depth: float = 0,
                hole_side: str = "auto") -> Any:
    """Тело OCCT с аналитическими рёбрами, без аппроксимации дуг сеткой."""
    start, end = extrusion_limits(document.offset_mm, depth, direction)
    entry_side = hole_entry_side(direction, hole_side)
    if document.plane not in ("XY", "XZ", "YZ"):
        raise ValueError("Некорректная плоскость")
    contours = ordered_contours(document.entities)
    validate_hole_depth(depth, hole_depth, has_holes=len(contours) > 1)
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_Transform,
    )
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.BRepTools import BRepTools
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_ShapeEnum, TopAbs_State
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    def xyz(point: Point) -> tuple[float, float, float]:
        x, y = point
        offset = start
        if document.plane == "XY":
            return x, y, offset
        if document.plane == "XZ":
            return x, offset, y
        return offset, x, y

    normal = {"XY": (0., 0., 1.), "XZ": (0., 1., 0.), "YZ": (1., 0., 0.)}[document.plane]
    plane = gp_Pln(gp_Pnt(*xyz((0., 0.))), gp_Dir(*normal))
    wires = []
    faces = []
    areas = []
    for contour in contours:
        wire = BRepBuilderAPI_MakeWire()
        for entity, reverse in contour:
            if entity.kind == "circle":
                axis = gp_Ax2(gp_Pnt(*xyz(entity.start)), gp_Dir(*normal))
                edge = BRepBuilderAPI_MakeEdge(gp_Circ(axis, entity.size))
            elif entity.kind == "line":
                p, q = (entity.end, entity.start) if reverse else (entity.start, entity.end)
                edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*xyz(p)), gp_Pnt(*xyz(q)))
            else:
                p = point_at(entity, 1 if reverse else 0)
                q = point_at(entity, 0 if reverse else 1)
                middle = point_at(entity, 0.5)
                arc = GC_MakeArcOfCircle(gp_Pnt(*xyz(p)), gp_Pnt(*xyz(middle)), gp_Pnt(*xyz(q)))
                if not arc.IsDone():
                    raise ValueError("CAD-ядро не смогло построить дугу")
                edge = BRepBuilderAPI_MakeEdge(arc.Value())
            if not edge.IsDone():
                raise ValueError("CAD-ядро не смогло построить ребро")
            wire.Add(edge.Edge())
            if not wire.IsDone():
                raise ValueError("CAD-ядро не смогло соединить рёбра контура")
        face_builder = BRepBuilderAPI_MakeFace(plane, wire.Wire(), True)
        if not face_builder.IsDone() or face_builder.Face().IsNull() or not BRepCheck_Analyzer(face_builder.Face()).IsValid():
            raise ValueError("CAD-ядро не смогло создать корректную грань контура")
        face = face_builder.Face()
        normalized = BRepTools.OuterWire_s(face)
        if normalized.IsNull():
            raise ValueError("Не удалось определить границу контура")
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        if not math.isfinite(props.Mass()) or props.Mass() <= 1e-12:
            raise ValueError("Площадь контура недопустима")
        wires.append(normalized)
        faces.append(face)
        areas.append(props.Mass())

    # Reject all contacts using exact CAD curves, independently of the sketch
    # diagnostic. A point on each boundary then unambiguously classifies it.
    containers: list[list[int]] = [[] for _ in contours]
    for i, contour in enumerate(contours):
        entity = contour[0][0]
        point = entity.end if entity.kind == "circle" else point_at(entity, 0)
        for j in range(i + 1, len(contours)):
            distance_check = BRepExtrema_DistShapeShape(wires[i], wires[j])
            distance_check.Perform()
            if not distance_check.IsDone() or distance_check.Value() <= 1e-7:
                raise ValueError("Контуры пересекаются или касаются")
        for j, face in enumerate(faces):
            if i == j:
                continue
            state = BRepClass_FaceClassifier(face, gp_Pnt(*xyz(point)), 1e-7).State()
            if state == TopAbs_State.TopAbs_IN:
                containers[i].append(j)
            elif state != TopAbs_State.TopAbs_OUT:
                raise ValueError("Не удалось определить вложенность контуров")
    outer = [i for i, parents in enumerate(containers) if not parents]
    if len(outer) != 1 or any(len(parents) != 1 or parents[0] != outer[0]
                              for i, parents in enumerate(containers) if i != outer[0]):
        raise ContourLayoutError("Нужен один внешний контур с отверстиями внутри; отдельные детали и вложенные острова не поддерживаются")
    builder = BRepBuilderAPI_MakeFace(faces[outer[0]])
    for i, wire in enumerate(wires):
        if i != outer[0]:
            builder.Add(TopoDS.Wire(wire.Reversed()))
    if builder.Face().IsNull() or not BRepCheck_Analyzer(builder.Face()).IsValid():
        raise ValueError("CAD-ядро не смогло создать грань с отверстиями")
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(builder.Face(), props)
    expected = areas[outer[0]] - sum(area for i, area in enumerate(areas) if i != outer[0])
    if expected <= 1e-12 or not math.isclose(props.Mass(), expected, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("Не удалось корректно вычесть отверстия")
    # Through holes use a single face. Blind pockets cut the outer prism from
    # the chosen side of the normal axis. All pockets share one depth and side.
    vec = gp_Vec(*(x * (end - start) for x in normal))
    base_face = faces[outer[0]] if hole_depth > 0 else builder.Face()
    prism = BRepPrimAPI_MakePrism(base_face, vec, True)
    if not prism.IsDone() or prism.Shape().IsNull() or not BRepCheck_Analyzer(prism.Shape()).IsValid():
        raise ValueError("CAD-ядро не смогло создать корректное тело")
    solid = prism.Shape()
    if hole_depth > 0:
        for i, pocket_face in enumerate(faces):
            if i == outer[0]:
                continue
            # A cutter starting at the lower coordinate removes inward from
            # that side; the shifted cutter removes inward from the upper side.
            shift = depth - hole_depth if entry_side == "positive" else 0.
            if shift:
                transform = gp_Trsf()
                transform.SetTranslation(gp_Vec(*(x * shift for x in normal)))
                pocket_shape = BRepBuilderAPI_Transform(pocket_face, transform, True).Shape()
            else:
                pocket_shape = pocket_face
            cutter = BRepPrimAPI_MakePrism(pocket_shape, gp_Vec(*(x * hole_depth for x in normal)), True)
            if not cutter.IsDone() or cutter.Shape().IsNull():
                raise ValueError("CAD-ядро не смогло построить объём отверстия")
            cut = BRepAlgoAPI_Cut(solid, cutter.Shape())
            cut.Build()
            if not cut.IsDone() or cut.Shape().IsNull() or not BRepCheck_Analyzer(cut.Shape()).IsValid():
                raise ValueError("CAD-ядро не смогло создать глухое отверстие")
            solid = cut.Shape()
    explorer = TopExp_Explorer(solid, TopAbs_ShapeEnum.TopAbs_SOLID)
    if not explorer.More():
        raise ValueError("Результат не является телом")
    explorer.Next()
    if explorer.More():
        raise ValueError("Получено несколько тел; поддерживается только одно")
    volume = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, volume)
    if not math.isfinite(volume.Mass()) or volume.Mass() <= 1e-12:
        raise ValueError("Объём тела нулевой или недопустим")
    hole_area = sum(area for i, area in enumerate(areas) if i != outer[0])
    expected_volume = areas[outer[0]] * depth - hole_area * (hole_depth or depth)
    if not math.isclose(volume.Mass(), expected_volume, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("Объём тела не соответствует глубине отверстий")
    return solid


def write_step(document: SketchDocument, depth: float, output: Path, direction: str = "positive", hole_depth: float = 0,
               hole_side: str = "auto") -> None:
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    solid = build_solid(document, depth, direction, hole_depth, hole_side)
    writer = STEPControl_Writer()
    if not Interface_Static.SetCVal_s("write.step.unit", "MM"):
        raise ValueError("Не удалось задать единицы STEP в миллиметрах")
    if writer.Transfer(solid, STEPControl_AsIs) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError("CAD-ядро не смогло подготовить STEP")
    if writer.Write(str(output)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError("CAD-ядро не смогло записать STEP")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (4, 5, 6, 7):
        return 2
    source, output, report = (Path(x) for x in args[:3])
    try:
        document = read_sketch(source)
        write_step(document, float(args[3]), output, args[4] if len(args) >= 5 else "positive",
                   float(args[5]) if len(args) >= 6 else 0, args[6] if len(args) == 7 else "auto")
        report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        return 0
    except (ImportError, OSError):
        code = "missing_cad"
    except ContourLayoutError:
        code = "contour_layout"
    except ValueError:
        code = "invalid_shape"
    except Exception:
        code = "unexpected"
    report.write_text(json.dumps({"status": "error", "code": code}), encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
