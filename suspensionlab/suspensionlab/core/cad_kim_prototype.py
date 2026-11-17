"""Минимальный независимый CAD-прототип для проверки KIM, не модель подвески."""
from __future__ import annotations

from typing import Any

from ..model.kim_format import _assembly, _part


def build_part(document: dict[str, Any]) -> Any:
    """Строит точное B-rep тестового цилиндра в локальной системе координат."""
    _part(document)
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    geometry = document["geometry"]
    return BRepPrimAPI_MakeCylinder(float(geometry["radius_mm"]), float(geometry["length_mm"])).Shape()


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
