"""Данные дискретного графика одного расчёта: без интерполяции и заполнения пропусков."""
from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from math import isfinite

from .analysis import CornerAnalysis
from .antiroll import AntiRollPoint
from .combined_checks import ComponentChecks
from .damper import LinearDamperCharacteristic, evaluate_linear_damping

# Порядок и имена совпадают с числовыми колонками таблицы; состояние остаётся в таблице.
PLOT_METRICS = (
    "camber", "toe", "spring_length", "spring_compression", "spring_force", "damper_length",
    "damper_ratio", "damper_speed", "damper_wheel_force", "damper_power",
)
ANTIROLL_METRICS = ("left_angle", "right_angle", "twist", "torque", "left_force", "right_force")


@dataclass(frozen=True)
class PlotPoint:
    travel_mm: float
    values: tuple[float | None, ...]
    conflict: bool = False


def _finite(value: float | None) -> float | None:
    return value if value is not None and isfinite(value) else None


def sweep_plot_points(
    analysis: CornerAnalysis,
    characteristic: LinearDamperCharacteristic | None = None,
    velocity_mm_s: float = 0.0,
) -> tuple[PlotPoint, ...]:
    """Переносит исходные значения без округления из расчёта, не из таблицы.

    Красная отметка означает только выявленный конфликт или ошибку элемента.
    У неизвестных пределов нет отметки: это не подтверждение безопасности.
    """
    points: list[PlotPoint] = []
    for point, sample in zip(analysis.sweep.points, analysis.samples, strict=True):
        if sample is None:
            points.append(PlotPoint(point.travel_mm, (None,) * len(PLOT_METRICS)))
            continue
        spring = sample.spring
        state = spring.state if spring is not None else None
        damper = sample.damper
        dynamics = None
        if characteristic is not None and damper is not None:
            # Нет данных для данной точки — не заменяем нулём.
            with suppress(ValueError):
                dynamics = evaluate_linear_damping(damper, characteristic, velocity_mm_s)
        conflict = bool(
            (spring is not None and (spring.error is not None or (state is not None and state.status == "coil_bind")))
            or (damper is not None and damper.has_detected_conflict)
        )
        values = (
            sample.geometry.camber_deg, sample.geometry.toe_deg,
            state.length_mm if state else None, state.compression_mm if state else None,
            state.force_n if state else None, damper.length_mm if damper else None,
            damper.motion_ratio if damper else None,
            dynamics.compression_velocity_mm_s if dynamics else None,
            dynamics.wheel_force_n if dynamics else None, dynamics.dissipated_power_w if dynamics else None,
        )
        points.append(PlotPoint(point.travel_mm, tuple(_finite(v) for v in values), conflict))
    return tuple(points)


def antiroll_plot_points(
    points: tuple[AntiRollPoint, ...],
    checks: list[tuple[ComponentChecks, ComponentChecks] | None],
) -> tuple[PlotPoint, ...]:
    """По горизонтали ход левого колеса; состояние обеих сторон проверяется отдельно.

    Отсутствие результатов проверки не является подтверждением безопасности.
    """
    result = []
    for point, pair in zip(points, checks, strict=True):
        state = point.state
        conflict = any(
            (check.spring is not None and check.spring.status in ("invalid", "coil_bind"))
            or (check.damper is not None and (check.damper.invalid or (
                check.damper.stroke is not None and check.damper.stroke.status != "inside")))
            for check in pair or ()
        )
        values = (state.left.arm_angle_deg, state.right.arm_angle_deg, state.twist_deg, state.torque_nm,
                  state.left.compression_force_n, state.right.compression_force_n) if state else (None,) * len(ANTIROLL_METRICS)
        result.append(PlotPoint(point.left_travel_mm, tuple(_finite(v) for v in values), conflict))
    return tuple(result)


def plot_segments(points: tuple[PlotPoint, ...], metric: int, metric_count: int = len(PLOT_METRICS)) -> tuple[tuple[int, int], ...]:
    """Только соседние решённые точки без обнаруженного конфликта; пропуски не соединяются."""
    if not 0 <= metric < metric_count or any(len(point.values) != metric_count for point in points):
        raise ValueError("Неизвестная величина графика или неполные данные")
    return tuple(
        (i - 1, i)
        for i in range(1, len(points))
        if not points[i - 1].conflict and not points[i].conflict
        and (first := points[i - 1].values[metric]) is not None and (second := points[i].values[metric]) is not None
        and isfinite(first) and isfinite(second)
        and isfinite(points[i - 1].travel_mm) and isfinite(points[i].travel_mm)
    )
