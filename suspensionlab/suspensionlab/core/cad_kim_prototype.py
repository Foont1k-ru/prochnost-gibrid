"""Минимальный независимый CAD-прототип для проверки KIM, не модель подвески."""
from __future__ import annotations

from typing import Any

from ..model.kim_format import _assembly, _part


def build_part(document: dict[str, Any]) -> Any:
    """Перестраивает только экспериментальную геометрию, не реальную деталь."""
    _part(document)
    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    geometry = document["geometry"]
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
    if document["version"] == "0.2":
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
