"""Изолированный OCCT worker: один аналитический контур -> STEP-тело в мм."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from ..model.sketch_contours import check_contours
from ..model.sketch_curves import NUMERIC_EPS_MM, distance, endpoints, point_at
from ..model.sketch_draft import Entity, Point
from ..model.sketch_io import SketchDocument, read_sketch


def ordered_contour(entities: tuple[Entity, ...]) -> tuple[tuple[Entity, bool], ...]:
    """Строго один замкнутый контур, направление каждого элемента явно задано."""
    report = check_contours(entities)
    if report.total_issues or report.closed_loops != 1:
        raise ValueError("Нужен один замкнутый контур без разрывов, пересечений и отверстий")
    if len(entities) == 1 and entities[0].kind == "circle":
        return ((entities[0], False),)
    if any(entity.kind == "circle" for entity in entities):
        raise ValueError("Несколько контуров и отверстия пока не поддерживаются")
    current = endpoints(entities[0])[0]
    start = current
    remaining = set(range(len(entities)))
    ordered: list[tuple[Entity, bool]] = []
    for step in range(len(entities)):
        matches = ([(0, 0)] if step == 0 else
                   [(i, j) for i in sorted(remaining) for j, p in enumerate(endpoints(entities[i]))
                    if distance(current, p) <= NUMERIC_EPS_MM])
        if len(matches) != 1:
            raise ValueError("Не удалось однозначно упорядочить контур")
        index, side = matches[0]
        remaining.remove(index)
        entity = entities[index]
        ordered.append((entity, side == 1))
        current = endpoints(entity)[1 - side]
    if remaining or distance(current, start) > NUMERIC_EPS_MM:
        raise ValueError("Контур не замкнут")
    return tuple(ordered)


def build_solid(document: SketchDocument, depth: float) -> Any:
    """Тело OCCT с аналитическими рёбрами, без аппроксимации дуг сеткой."""
    if not math.isfinite(depth) or not 0 < depth <= 1_000_000:
        raise ValueError("Глубина должна быть больше нуля и не более 1 000 000 мм")
    if document.plane not in ("XY", "XZ", "YZ") or not math.isfinite(document.offset_mm):
        raise ValueError("Некорректная плоскость")
    contour = ordered_contour(document.entities)
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt, gp_Vec
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    def xyz(point: Point) -> tuple[float, float, float]:
        x, y = point
        offset = document.offset_mm
        if document.plane == "XY":
            return x, y, offset
        if document.plane == "XZ":
            return x, offset, y
        return offset, x, y

    normal = {"XY": (0., 0., 1.), "XZ": (0., 1., 0.), "YZ": (1., 0., 0.)}[document.plane]
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
    face = BRepBuilderAPI_MakeFace(wire.Wire(), True)
    if not face.IsDone() or face.Face().IsNull() or not BRepCheck_Analyzer(face.Face()).IsValid():
        raise ValueError("CAD-ядро не смогло создать корректную грань контура")
    vec = gp_Vec(*(x * depth for x in normal))
    prism = BRepPrimAPI_MakePrism(face.Face(), vec, True)
    if not prism.IsDone() or prism.Shape().IsNull() or not BRepCheck_Analyzer(prism.Shape()).IsValid():
        raise ValueError("CAD-ядро не смогло создать корректное тело")
    solid = prism.Shape()
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
    return solid


def write_step(document: SketchDocument, depth: float, output: Path) -> None:
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    solid = build_solid(document, depth)
    writer = STEPControl_Writer()
    if not Interface_Static.SetCVal_s("write.step.unit", "MM"):
        raise ValueError("Не удалось задать единицы STEP в миллиметрах")
    if writer.Transfer(solid, STEPControl_AsIs) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError("CAD-ядро не смогло подготовить STEP")
    if writer.Write(str(output)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError("CAD-ядро не смогло записать STEP")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4:
        return 2
    source, output, report = (Path(x) for x in args[:3])
    try:
        document = read_sketch(source)
        write_step(document, float(args[3]), output)
        report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        return 0
    except (ImportError, OSError):
        code = "missing_cad"
    except ValueError:
        code = "invalid_shape"
    except Exception:
        code = "unexpected"
    report.write_text(json.dumps({"status": "error", "code": code}), encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
