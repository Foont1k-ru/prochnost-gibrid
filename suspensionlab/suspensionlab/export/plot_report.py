"""Снимок численных точек графика для отдельного CSV, без интерполяции."""
from __future__ import annotations

from math import isfinite

from ..core.sweep_plot import PlotPoint
from ..i18n import tr


def plot_number(value: float | None) -> str:
    """Краткая запись с восстановлением значения float; отсутствие — прочерк, не ноль."""
    return repr(float(value)) if value is not None and isfinite(value) else "—"


def plot_report_rows(
    points: tuple[PlotPoint, ...],
    travel_label: str,
    metric_labels: tuple[str, ...],
    context_labels: tuple[str, ...],
    context_rows: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Все величины исходной сетки и контекст по каждой строке, включая неудачи.

    Флаг описывает только обнаруженные конфликты заданных элементов. Он не
    означает, что другие пределы были заданы или что путь безопасен.
    """
    if (not points or not metric_labels or len(context_rows) != len(points)
            or any(len(point.values) != len(metric_labels) or not isfinite(point.travel_mm) for point in points)
            or any(len(row) != len(context_labels) for row in context_rows)):
        raise ValueError(tr("export.no_results"))
    columns = (travel_label, *metric_labels, tr("export.plot_conflict"), *context_labels)
    rows = []
    for point, context in zip(points, context_rows, strict=True):
        available = any(value is not None and isfinite(value) for value in point.values)
        status = tr("export.plot_conflict_yes" if point.conflict else
                    "export.plot_conflict_none" if available else "export.plot_conflict_missing")
        rows.append((plot_number(point.travel_mm), *(plot_number(value) for value in point.values), status, *context))
    return columns, tuple(rows)
