"""Условные компоновочные схемы: не геометрия реальной трансмиссии."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from ..model.entities import Project

Point3 = tuple[float, float, float]
LAYOUTS = ("unspecified", "transverse_front", "longitudinal_transaxle", "longitudinal_transfer")


@dataclass(frozen=True)
class LayoutComponent:
    """Условный прямоугольный объём; границы — иллюстрация, не размеры агрегата."""
    kind: str
    low: Point3
    high: Point3


@dataclass(frozen=True)
class LayoutShaft:
    """Условный кардан к редуктору; полуоси находятся в геометрии осей."""
    role: str
    start: Point3
    end: Point3


@dataclass(frozen=True)
class LayoutDiagram:
    components: tuple[LayoutComponent, ...]
    shafts: tuple[LayoutShaft, ...]
    status: str


def layout_topology_status(layout: str, front_driven: bool, rear_driven: bool) -> str:
    """Статус только для выбранной условной схемы, без проверки геометрии."""
    if layout == "unspecified":
        return "unspecified"
    if layout not in LAYOUTS:
        return "unsupported"
    if layout in ("transverse_front", "longitudinal_transaxle") and rear_driven and not front_driven:
        return "incompatible"
    return "ok"


def layout_diagram(project: Project) -> LayoutDiagram:
    """Строит учебную схему относительно передней оси: X вперёд, задняя ось на −базе.

    Никаких пользовательских точек не меняет. Неизвестная компоновка и
    несовместимые входы не превращаются в выбранную автоматически схему.
    """
    layout = project.vehicle.powertrain_layout
    front, rear = project.front, project.rear
    status = layout_topology_status(layout, front.drivetrain.driven, rear.drivetrain.driven)
    if status != "ok":
        return LayoutDiagram((), (), status)
    base = project.vehicle.wheelbase_mm
    if not isfinite(base) or base <= 0:
        return LayoutDiagram((), (), "invalid")
    f = front.hardpoints.get("differential_center")
    r = rear.hardpoints.get("pinion_center" if rear.is_live_axle else "differential_center")
    if (front.drivetrain.driven and f is None) or (rear.drivetrain.driven and r is None):
        return LayoutDiagram((), (), "invalid")
    if any(p is not None and not all(isfinite(v) for v in p.as_tuple()) for p in (f, r)):
        return LayoutDiagram((), (), "invalid")
    fx = f.x if f else 0.0
    fz = f.z if f else 260.0
    front_diff: Point3 = (fx, f.y if f else 0.0, fz)
    rear_diff: Point3 = (r.x - base, r.y, r.z) if r else (-base, 0.0, fz)
    shafts: list[LayoutShaft] = []
    parts: tuple[LayoutComponent, ...]
    if layout == "transverse_front":
        parts = (
            LayoutComponent("engine", (fx - 160, 90, fz), (fx + 220, 650, fz + 360)),
            LayoutComponent("gearbox", (fx - 160, -260, fz - 40), (fx + 150, 90, fz + 200)),
        )
        if rear.drivetrain.driven:
            shafts.append(LayoutShaft("rear", front_diff, rear_diff))
    elif layout == "longitudinal_transaxle":
        parts = (
            LayoutComponent("engine", (fx + 100, -230, fz), (fx + 700, 230, fz + 380)),
            LayoutComponent("transaxle", (fx - 550, -180, fz - 40), (fx + 100, 180, fz + 200)),
        )
        if rear.drivetrain.driven:
            shafts.append(LayoutShaft("rear", (fx - 550, 0.0, fz), rear_diff))
    else:
        split_x = -0.38 * base
        parts = (
            LayoutComponent("engine", (fx - 300, -230, fz), (fx + 300, 230, fz + 380)),
            LayoutComponent("gearbox", (fx - 820, -180, fz - 40), (fx - 300, 180, fz + 200)),
            LayoutComponent("transfer", (split_x - 110, -180, fz - 50), (split_x + 110, 180, fz + 180)),
        )
        transfer: Point3 = (split_x, 0.0, fz)
        if front.drivetrain.driven:
            shafts.append(LayoutShaft("front", transfer, front_diff))
        if rear.drivetrain.driven:
            shafts.append(LayoutShaft("rear", transfer, rear_diff))
    return LayoutDiagram(parts, tuple(shafts), "ok")
