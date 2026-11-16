"""Полные данные сравнения осей по рассчитанным строкам."""
from __future__ import annotations

from ..core.axis_alignment import AxisAlignmentRow, AxisLimitCheck, AxisLimits, AxisMaxima
from ..i18n import tr
from .csv_report import CSVReport


def axis_alignment_rows(rows: tuple[AxisAlignmentRow, ...], states: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    if not rows or len(rows) != len(states):
        raise ValueError(tr("export.no_results"))
    columns = tuple(tr(f"axis_alignment.column.{key}") for key in ("row", "travel", "angle", "lower", "upper", "lower_pair", "upper_pair", "lower_axial", "upper_axial",
                            "status", "source"))
    result = []
    for index, (row, state) in enumerate(zip(rows, states, strict=True), 1):
        value = row.result
        result.append((str(index), repr(row.travel_mm), repr(value.angle_deg) if value else "—",
                       repr(value.lower_offset_mm) if value else "—", repr(value.upper_offset_mm) if value else "—",
                       repr(value.lower_pair_distance_mm) if value else "—", repr(value.upper_pair_distance_mm) if value else "—",
                       repr(value.lower_axial_mm) if value else "—", repr(value.upper_axial_mm) if value else "—",
                       tr(f"axis_alignment.status.{row.status}"), state))
    return columns, tuple(result)


def with_axis_limits(report: CSVReport, checks: tuple[AxisLimitCheck, ...], limits: AxisLimits,
                     maxima: AxisMaxima) -> CSVReport:
    """Снимок всех строк и пользовательских критериев; без фильтрации и округления."""
    if len(report.rows) != len(checks):
        raise ValueError(tr("export.no_results"))
    labels = tuple(tr(f"axis_alignment.limits.column.{key}") for key in ("angle", "lower", "upper", "combined"))
    values = tuple((*row, *(tr(f"axis_alignment.limits.status.{v}") for v in (check.angle, check.lower, check.upper)),
                    tr(f"axis_alignment.limits.combined.{check.combined}"))
                   for row, check in zip(report.rows, checks, strict=True))
    metadata = tuple((tr(f"axis_alignment.limits.field.{key}"), repr(value) if value is not None else tr("axis_alignment.limits.unset"))
                     for key, value in (("angle", limits.angle_deg), ("lower", limits.lower_distance_mm),
                                        ("upper", limits.upper_distance_mm)))
    maximum_metadata = tuple(
        (tr(f"axis_alignment.maximum_report.{key}"),
         tr("axis_alignment.maximum_report.value", value=repr(extremum.value), travel=repr(extremum.travel_mm),
            row=extremum.row + 1) if extremum is not None else tr("axis_alignment.maximum_report.unavailable"))
        for key, extremum in (("angle", maxima.angle), ("lower", maxima.lower), ("upper", maxima.upper)))
    return CSVReport((*report.metadata, *metadata, *maximum_metadata,
                      (tr("axis_alignment.limits.scope_label"), tr("axis_alignment.limits.notice"))),
                     (*report.columns, *labels), values)
