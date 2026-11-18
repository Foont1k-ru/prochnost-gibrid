"""Изолированный OCCT worker: аналитические контуры -> STEP-тело в мм."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from ..model.sketch_contours import ordered_contour_indices
from ..model.sketch_curves import point_at
from ..model.sketch_draft import Entity, Point
from ..model.sketch_extrude_settings import (
    HoleOverride,
    extrusion_limits,
    hole_entry_side,
    validate_hole_depth,
    validate_hole_overrides,
)
from ..model.sketch_io import SketchDocument, read_sketch


class HoleOverrideError(ValueError):
    """Параметры назначены внешнему контуру или дважды одному отверстию."""


class ContourLayoutError(ValueError):
    """Отдельные внешние контуры или вложенные острова не поддерживаются."""


def ordered_contour(entities: tuple[Entity, ...]) -> tuple[tuple[Entity, bool], ...]:
    """Совместимый помощник для единственного контура."""
    contours = ordered_contours(entities)
    if len(contours) != 1:
        raise ValueError("Нужен один замкнутый контур")
    return contours[0]


def ordered_contours(entities: tuple[Entity, ...]) -> tuple[tuple[tuple[Entity, bool], ...], ...]:
    """Совместимый вид без индексов; вложенность проверяет CAD-ядро."""
    return tuple(tuple((entities[index], reverse) for index, reverse in contour)
                 for contour in ordered_contour_indices(entities))


def build_solid(document: SketchDocument, depth: float, direction: str = "positive", hole_depth: float = 0,
                hole_side: str = "auto", hole_overrides: tuple[HoleOverride, ...] = ()) -> Any:
    """Тело OCCT с аналитическими рёбрами, без аппроксимации дуг сеткой."""
    start, end = extrusion_limits(document.offset_mm, depth, direction)
    entry_side = hole_entry_side(direction, hole_side)
    if document.plane not in ("XY", "XZ", "YZ"):
        raise ValueError("Некорректная плоскость")
    indexed_contours = ordered_contour_indices(document.entities)
    contours = tuple(tuple((document.entities[index], reverse) for index, reverse in contour)
                     for contour in indexed_contours)
    validate_hole_depth(depth, hole_depth, has_holes=len(contours) > 1)
    validate_hole_overrides(depth, direction, hole_overrides, len(document.entities))
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
    # A selected element identifies its entire loop. The CAD classifier must
    # reject the external boundary and two settings for the same loop.
    settings: dict[int, tuple[float, str]] = {}
    by_element = {index: i for i, contour in enumerate(indexed_contours) for index, _ in contour}
    for element_index, override_depth, override_side in hole_overrides:
        loop = by_element[element_index]
        if loop == outer[0] or loop in settings:
            raise HoleOverrideError("Настройте разные внутренние контуры, не внешний")
        settings[loop] = (override_depth, hole_entry_side(direction, override_side))
    hole_settings = {i: settings.get(i, (hole_depth, entry_side)) for i in range(len(contours)) if i != outer[0]}
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
    # Fast path for all-through profiles; mixed or blind pockets use cuts.
    vec = gp_Vec(*(x * (end - start) for x in normal))
    all_through = all(item[0] == 0 for item in hole_settings.values())
    base_face = builder.Face() if all_through else faces[outer[0]]
    prism = BRepPrimAPI_MakePrism(base_face, vec, True)
    if not prism.IsDone() or prism.Shape().IsNull() or not BRepCheck_Analyzer(prism.Shape()).IsValid():
        raise ValueError("CAD-ядро не смогло создать корректное тело")
    solid = prism.Shape()
    if not all_through:
        for i, pocket_face in enumerate(faces):
            if i == outer[0]:
                continue
            configured_depth, configured_side = hole_settings[i]
            cut_depth = configured_depth or depth
            # Through cutters occupy the full body regardless of entry side.
            shift = depth - cut_depth if configured_side == "positive" else 0.
            if shift:
                transform = gp_Trsf()
                transform.SetTranslation(gp_Vec(*(x * shift for x in normal)))
                pocket_shape = BRepBuilderAPI_Transform(pocket_face, transform, True).Shape()
            else:
                pocket_shape = pocket_face
            cutter = BRepPrimAPI_MakePrism(pocket_shape, gp_Vec(*(x * cut_depth for x in normal)), True)
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
    removed_volume = sum(areas[i] * (config[0] or depth) for i, config in hole_settings.items())
    expected_volume = areas[outer[0]] * depth - removed_volume
    if not math.isclose(volume.Mass(), expected_volume, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("Объём тела не соответствует глубине отверстий")
    return solid


def write_step(document: SketchDocument, depth: float, output: Path, direction: str = "positive", hole_depth: float = 0,
               hole_side: str = "auto", hole_overrides: tuple[HoleOverride, ...] = ()) -> None:
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    solid = build_solid(document, depth, direction, hole_depth, hole_side, hole_overrides)
    writer = STEPControl_Writer()
    if not Interface_Static.SetCVal_s("write.step.unit", "MM"):
        raise ValueError("Не удалось задать единицы STEP в миллиметрах")
    if writer.Transfer(solid, STEPControl_AsIs) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError("CAD-ядро не смогло подготовить STEP")
    if writer.Write(str(output)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError("CAD-ядро не смогло записать STEP")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (4, 5, 6, 7, 8):
        return 2
    source, output, report = (Path(x) for x in args[:3])
    try:
        document = read_sketch(source)
        overrides = ()
        if len(args) == 8:
            path = Path(args[7])
            if path.stat().st_size > 64_000:
                raise ValueError("Слишком большой список отверстий")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("Некорректный список отверстий")
            overrides = tuple(data)
        write_step(document, float(args[3]), output, args[4] if len(args) >= 5 else "positive",
                   float(args[5]) if len(args) >= 6 else 0, args[6] if len(args) >= 7 else "auto", overrides)
        report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        return 0
    except (ImportError, OSError):
        code = "missing_cad"
    except HoleOverrideError:
        code = "invalid_hole_override"
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
