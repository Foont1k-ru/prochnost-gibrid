"""Отчёт рассчитанных координат одной точки для всех строк хода."""
from __future__ import annotations

from math import isfinite

from ..core.scene3d import POINT_CODES, Scene3D
from ..i18n import tr
from .plot_report import plot_number


def point_position_rows(
    code: str, travels: tuple[float, ...], scenes: tuple[Scene3D | None, ...], states: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """В том же порядке и числе строк; пропуски и состояния не подменяются нулями."""
    if (code not in POINT_CODES or not travels or len(travels) != len(scenes) or len(travels) != len(states)
            or not all(isfinite(travel) for travel in travels)):
        raise ValueError(tr("export.no_results"))
    columns = tuple(tr(f"analysis.scene3d.point_report.column.{key}") for key in (
        "row", "travel", "x", "y", "z", "availability", "state"))
    rows = []
    for i, (travel, scene, state) in enumerate(zip(travels, scenes, states, strict=True), 1):
        if scene is not None and scene.travel_mm != travel:
            raise ValueError(tr("export.no_results"))
        point = scene.point(code) if scene is not None else None
        if point is not None and not all(isfinite(value) for value in point):
            raise ValueError(tr("export.no_results"))
        status = "frame_missing" if scene is None else "point_missing" if point is None else "available"
        values = tuple(plot_number(value) for value in point) if point is not None else ("—", "—", "—")
        rows.append((str(i), plot_number(travel), *values,
                     tr(f"analysis.scene3d.point_report.availability.{status}"), state))
    return columns, tuple(rows)
