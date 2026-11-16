"""Данные плоского наложения хранимых точек без отражения и интерполяции."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ..model.point_csv import PointRecord
from .snapshot_compare import PointComparison

Projection = Literal["front", "side", "top"]
MAX_COORD_MM = 1_000_000_000.0


@dataclass(frozen=True, slots=True)
class OverlayPoint:
    row: int  # индекс в полной таблице сравнения
    source: Literal["A", "B"]
    u: float
    v: float


@dataclass(frozen=True, slots=True)
class OverlayData:
    points: tuple[OverlayPoint, ...]
    omitted_rows: tuple[int, ...]
    connected_rows: tuple[int, ...]


def project_point(xyz: tuple[float, float, float], view: Projection) -> tuple[float, float]:
    """Ориентация как на основной схеме: +X и +Y влево, +Z/+Y вверх."""
    x, y, z = xyz
    if view == "front":
        return -y, z
    if view == "side":
        return -x, z
    if view == "top":
        return -x, y
    raise ValueError("unknown projection")


def make_overlay(rows: tuple[PointComparison, ...], role: str, view: Projection) -> OverlayData:
    """Пропускает некорректные строки и экстремальные координаты целиком.

    Разные представления отображаются по отдельности, но их соединение не
    создаётся здесь и не должно строиться в виджете. Координаты в системе оси.
    """
    if role not in ("front", "rear") or view not in ("front", "side", "top"):
        raise ValueError("unknown axle or projection")
    points: list[OverlayPoint] = []
    omitted = []
    connected = []
    for index, row in enumerate(rows):
        if row.role != role:
            continue
        records: tuple[tuple[Literal["A", "B"], PointRecord | None], ...] = (("A", row.old), ("B", row.new))
        if row.status == "invalid" or any(
            p is not None and any(not math.isfinite(c) or abs(c) > MAX_COORD_MM for c in p.xyz)
            for _, p in records
        ):
            omitted.append(index)
            continue
        if row.status in ("changed", "unchanged") and row.old is not None and row.new is not None:
            connected.append(index)
        for source, point in records:
            if point is not None:
                u, v = project_point(point.xyz, view)
                points.append(OverlayPoint(index, source, u, v))
    return OverlayData(tuple(points), tuple(omitted), tuple(connected))
