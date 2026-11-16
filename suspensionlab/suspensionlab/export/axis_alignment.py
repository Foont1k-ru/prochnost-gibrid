"""Полные данные сравнения осей по рассчитанным строкам."""
from __future__ import annotations

from ..core.axis_alignment import AxisAlignmentRow
from ..i18n import tr


def axis_alignment_rows(rows: tuple[AxisAlignmentRow, ...], states: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    if not rows or len(rows) != len(states):
        raise ValueError(tr("export.no_results"))
    columns = tuple(tr(f"axis_alignment.column.{key}") for key in ("row", "travel", "angle", "lower", "upper", "status", "source"))
    result = []
    for index, (row, state) in enumerate(zip(rows, states, strict=True), 1):
        value = row.result
        result.append((str(index), repr(row.travel_mm), repr(value.angle_deg) if value else "—",
                       repr(value.lower_offset_mm) if value else "—", repr(value.upper_offset_mm) if value else "—",
                       tr(f"axis_alignment.status.{row.status}"), state))
    return columns, tuple(result)
