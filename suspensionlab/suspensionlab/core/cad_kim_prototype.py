"""Минимальный независимый CAD-прототип для проверки KIM, не модель подвески."""
from __future__ import annotations

from typing import Any

from ..model.kim_format import _assembly, _part


def build_part(document: dict[str, Any]) -> Any:
    """Перестраивает только экспериментальную геометрию, не реальную деталь."""
    _part(document)
    from OCP.BRep import BRep_Builder
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
    for inner in points[:2]:
        direction = [float(b) - float(a) for a, b in zip(inner, outer, strict=True)]
        axis = gp_Ax2(gp_Pnt(*map(float, inner)), gp_Dir(*direction))
        rod = BRepPrimAPI_MakeCylinder(axis, float(geometry["radius_mm"]), math.dist(inner, outer)).Shape()
        builder.Add(compound, rod)
    return compound


def build_assembly(document: dict[str, Any]) -> Any:
    """Создаёт соединение перенесённых экземпляров, не связывая их со схемой."""
    _assembly(document)
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
