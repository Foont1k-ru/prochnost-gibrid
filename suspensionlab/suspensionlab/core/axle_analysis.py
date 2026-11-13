"""Сводный анализ двух сторон передней двухрычажной оси на общем ходе."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..model.entities import Axle, Vehicle
from .analysis import CornerAnalysis, analyze_corner
from .double_wishbone import DoubleWishbone, KinematicsError
from .roll_center import symmetric_roll_center_height
from .scrub_analysis import ScrubSignAnalysis, check_scrub_signs


@dataclass(frozen=True)
class AxleSample:
    """Колея и проекционный ЦК на одинаковом ходе левой и правой сторон."""

    travel_mm: float
    track_mm: float | None
    track_change_mm: float | None
    projected_roll_center_z_mm: float | None
    roll_center_error: str | None


@dataclass(frozen=True)
class AxleAnalysis:
    """Обе стороны и диагностические сведения по дискретному свипу."""

    left: CornerAnalysis
    right: CornerAnalysis
    samples: tuple[AxleSample, ...]
    left_scrub: ScrubSignAnalysis
    right_scrub: ScrubSignAnalysis


def analyze_symmetric_axle(
    axle: Axle,
    vehicle: Vehicle,
    travels_mm: list[float],
    *,
    spring_mount: Literal["lower_arm"] | None = None,
    zero_tolerance_mm: float = 1e-6,
    max_step_mm: float = 2.0,
) -> AxleAnalysis:
    """Анализирует равный ход обеих сторон; кузов и земля неподвижны.

    Полуоси здесь не рассчитываются: для каждой стороны нужны собственные
    явно заданные оси и границы. Для раздельного хода вызовите расчёт
    отдельных сторон и `roll_center_from_projected_motion`.
    """
    left = analyze_corner(axle, vehicle, travels_mm, side="left", spring_mount=spring_mount, max_step_mm=max_step_mm)
    right = analyze_corner(axle, vehicle, travels_mm, side="right", spring_mount=spring_mount, max_step_mm=max_step_mm)
    model = DoubleWishbone(axle, "left")
    static_track = 2.0 * model.center0[1]
    samples: list[AxleSample] = []
    left_scrub_values: list[tuple[float, float | None]] = []
    right_scrub_values: list[tuple[float, float | None]] = []
    for travel, ls, rs in zip(travels_mm, left.samples, right.samples, strict=True):
        left_scrub_values.append((travel, ls.geometry.scrub_radius_mm if ls is not None else None))
        right_scrub_values.append((travel, rs.geometry.scrub_radius_mm if rs is not None else None))
        if ls is None or rs is None:
            samples.append(AxleSample(travel, None, None, None, "Решение для одной или обеих сторон не получено"))
            continue
        track = float(ls.pose.center[1] - rs.pose.center[1])
        try:
            roll_center = symmetric_roll_center_height(model, ls.pose)
            error = None
        except KinematicsError as exc:
            roll_center = None
            error = exc.reason
        samples.append(AxleSample(travel, track, track - static_track, roll_center, error))
    return AxleAnalysis(
        left=left,
        right=right,
        samples=tuple(samples),
        left_scrub=check_scrub_signs(left_scrub_values, zero_tolerance_mm=zero_tolerance_mm),
        right_scrub=check_scrub_signs(right_scrub_values, zero_tolerance_mm=zero_tolerance_mm),
    )
