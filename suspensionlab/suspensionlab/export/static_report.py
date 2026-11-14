"""Дискретный отчёт о нулевом ходе; не проверка реальной сборки."""
from __future__ import annotations

from math import dist

from ..core.analysis import CornerSample
from ..i18n import tr
from ..model.entities import Axle
from .plot_report import plot_number


def static_report_rows(
    sample: CornerSample, axle: Axle, side: str,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Исходные float без округления; отсутствующие величины не превращаются в ноль."""
    if sample.pose.travel_mm != 0 or side not in ("left", "right"):
        raise ValueError("Для отчёта требуется нулевой ход и выбранная сторона")
    columns = tuple(tr(f"analysis.static.report.column.{key}") for key in ("metric", "value", "unit", "note"))
    rows: list[tuple[str, ...]] = []
    missing = tr("analysis.static.report.missing")
    disabled = tr("analysis.static.report.disabled")

    def number(key: str, value: float | None, unit: str, note: str = "") -> None:
        rows.append((tr(f"analysis.static.report.metric.{key}"), plot_number(value), unit, note))

    def state(key: str, value: str, note: str = "") -> None:
        rows.append((tr(f"analysis.static.report.metric.{key}"), value, "", note))

    def coordinates(code: str, enabled: bool) -> None:
        point = axle.hardpoints.get(code) if enabled else None
        values = (point.x, point.y * (1 if side == "left" else -1), point.z) if point is not None else (None,) * 3
        for axis, value in zip(("x", "y", "z"), values, strict=True):
            number(f"{code}_{axis}", value, "мм", "" if point is not None else (missing if enabled else disabled))

    number("travel", sample.pose.travel_mm, "мм")
    spring = sample.spring
    for code in ("spring_lo", "spring_up"):
        coordinates(code, spring is not None)
    state("spring_status", disabled if spring is None else (
        spring.error or (tr(f"analysis.spring_status.{spring.state.status}") if spring.state is not None else missing)))
    spring_state = spring.state if spring is not None else None
    distance = None
    if spring is not None and "spring_lo" in axle.hardpoints and "spring_up" in axle.hardpoints:
        low, high = axle.hardpoints["spring_lo"], axle.hardpoints["spring_up"]
        distance = dist((low.x, low.y, low.z), (high.x, high.y, high.z))
    reason = disabled if spring is None else missing
    number("spring_mount_distance", distance, "мм", tr("analysis.static.report.mount_note") if distance is not None else reason)
    number("spring_offset", spring_state.length_mm - distance if spring_state is not None and distance is not None else None,
           "мм", tr("analysis.static.report.offset_note") if spring_state is not None and distance is not None else reason)
    for key, value, unit in (("spring_length", spring_state.length_mm if spring_state else None, "мм"),
                             ("spring_compression", spring_state.compression_mm if spring_state else None, "мм"),
                             ("spring_force", spring_state.force_n if spring_state else None, "Н"),
                             ("spring_clearance", spring_state.coil_clearance_mm if spring_state else None, "мм")):
        number(key, value, unit, "" if value is not None else reason)
    damper = sample.damper
    for code in ("damper_lo", "damper_up"):
        coordinates(code, damper is not None)
    stroke = damper.stroke if damper is not None else None
    state("damper_status", disabled if damper is None else (
        damper.error or tr(f"analysis.damper_status.{stroke.status}" if stroke else "analysis.damper_status.unknown")))
    reason = disabled if damper is None else missing
    for key, value, unit in (("damper_length", damper.length_mm if damper else None, "мм"),
                             ("damper_ratio", damper.motion_ratio if damper else None, ""),
                             ("damper_compression_clearance", stroke.compression_clearance_mm if stroke else None, "мм"),
                             ("damper_extension_clearance", stroke.extension_clearance_mm if stroke else None, "мм")):
        number(key, value, unit, "" if value is not None else reason)
    return columns, tuple(rows)
