"""Отчёт точек сравнения кандидата с исходными состояниями расчёта."""
from __future__ import annotations

from ..core.damper_range import CandidateComparison
from ..i18n import tr
from .plot_report import plot_number


def candidate_report_rows(result: CandidateComparison, source_states: tuple[str, ...]) -> tuple[
    tuple[str, ...], tuple[tuple[str, ...], ...]
]:
    """Использует единые статусы сравнения; сохраняет доступные float без округления."""
    if not result.points or len(result.points) != len(source_states):
        raise ValueError(tr("export.no_results"))
    columns = tuple(tr(f"damper_candidate.report.column.{key}") for key in (
        "row", "travel", "length", "compression", "extension", "candidate", "stop", "source"))
    rows = []
    for index, (point, source) in enumerate(zip(result.points, source_states, strict=True), 1):
        stroke = point.stroke
        rows.append((str(index), plot_number(point.travel_mm), plot_number(point.length_mm),
                     plot_number(stroke.compression_clearance_mm if stroke else None),
                     plot_number(stroke.extension_clearance_mm if stroke else None),
                     tr(f"damper_candidate.report.status.{point.status}"),
                     tr(f"analysis.damper_status.{stroke.status}") if stroke else "—", source))
    return columns, tuple(rows)
