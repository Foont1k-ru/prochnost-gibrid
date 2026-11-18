"""Построчный отчёт предварительного сравнения пружины."""
from __future__ import annotations

from ..core.spring_candidate import SpringComparison
from ..i18n import tr
from .plot_report import plot_number


def spring_candidate_report_rows(
    comparison: SpringComparison, source: tuple[tuple[float, float | None], ...], states: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Сохраняет обе длины, подписанные разности и исходные состояния без округления."""
    if not comparison.points or len(comparison.points) != len(source) or len(source) != len(states):
        raise ValueError(tr("export.no_results"))
    columns = tuple(tr(f"spring_candidate.report.column.{key}") for key in (
        "row", "travel", "original", "candidate", "coil", "compression", "status", "source", "force", "force_status"))
    rows = []
    for index, (point, (travel, original), source_state) in enumerate(zip(comparison.points, source, states, strict=True), 1):
        expected = (comparison.candidate.installed_mm + (original - comparison.reference_installed_mm)
                    if original is not None else None)
        if (travel != point.travel_mm or expected != point.length_mm
                or ((original is None) != (point.status == "missing"))):
            raise ValueError(tr("export.no_results"))
        rows.append((str(index), plot_number(travel), plot_number(original), plot_number(point.length_mm),
                     plot_number(point.coil_clearance_mm), plot_number(point.compression_mm),
                     tr(f"spring_candidate.report.status.{point.status}"), source_state,
                     plot_number(point.force_n), tr(f"spring_candidate.force.status.{point.force_status}")))
    return columns, tuple(rows)
