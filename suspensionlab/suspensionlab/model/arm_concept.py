"""Черновик рычага по схеме: параметры и 2D-эскиз, не CAD или прочностной расчёт."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .entities import Project
from .kim_format import KimFormatError, make_lower_arm_prototype

ArmStyle = Literal["tube", "sheet"]
Point3 = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class ArmConcept:
    """Только снимок трёх точек и введённые параметры условного эскиза."""

    style: ArmStyle
    source_type: str
    points: tuple[Point3, Point3, Point3]
    radius_mm: float
    wall_mm: float
    sheet_mm: float
    lengths_mm: tuple[float, float]
    triangle_area_mm2: float


def make_arm_concept(project: Project, style: ArmStyle, radius_mm: float,
                     wall_mm: float, sheet_mm: float) -> ArmConcept:
    """Из существующих округлённых точек; исходный проект не меняется.

    Размеры — только вход пользователя. Эскиз не содержит реальных труб,
    штамповки, соединений или проверки конструктивной пригодности.
    """
    if style not in ("tube", "sheet"):
        raise KimFormatError("unknown concept style")
    values = (radius_mm, wall_mm, sheet_mm)
    try:
        invalid = any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                      not math.isfinite(v) or not 0.01 <= v <= 10000 for v in values)
    except (OverflowError, TypeError) as error:
        raise KimFormatError("invalid concept dimensions") from error
    if invalid:
        raise KimFormatError("invalid concept dimensions")
    if style == "tube" and radius_mm - wall_mm < 0.01:
        raise KimFormatError("tube wall must leave at least 0.01 mm inner radius")
    prototype = make_lower_arm_prototype("concept", "concept", project, radius_mm)
    source = prototype["geometry"]["source"]
    coords = source["coordinates_mm"]
    first: Point3 = tuple(coords[0])  # type: ignore[assignment]
    second: Point3 = tuple(coords[1])  # type: ignore[assignment]
    outer: Point3 = tuple(coords[2])  # type: ignore[assignment]
    a = tuple(second[i] - first[i] for i in range(3))
    b = tuple(outer[i] - first[i] for i in range(3))
    cross = (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0])
    area = math.hypot(*cross) / 2
    if style == "sheet" and area < 0.01:
        raise KimFormatError("degenerate sheet outline")
    return ArmConcept(style=style, source_type=source["suspension_type"], points=(first, second, outer),
                      radius_mm=float(radius_mm), wall_mm=float(wall_mm), sheet_mm=float(sheet_mm),
                      lengths_mm=(math.dist(first, outer), math.dist(second, outer)), triangle_area_mm2=area)
