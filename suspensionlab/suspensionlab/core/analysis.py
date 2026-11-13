"""Расчёт частичного свипа одного колеса двухрычажной оси.

Это библиотечный интерфейс, не связанный с виджетами или файловой системой.
Его результат явно перечисляет допущения и отсутствие исходных данных.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np

from ..model.entities import Axle, Vehicle
from .double_wishbone import DoubleWishbone, KinematicsError, Pose
from .drivetrain import (
    HalfshaftGeometry,
    HalfshaftLimits,
    HalfshaftMetrics,
    HalfshaftViolation,
    check_halfshaft,
    halfshaft_metrics,
)
from .metrics import CornerDerivatives, CornerMetrics, corner_derivatives, corner_metrics
from .side_view import LongitudinalScenario, SideMetrics, evaluate_side_scenario
from .spring_characteristics import (
    BumpStopCharacteristic,
    BumpStopState,
    SpringCharacteristic,
    SpringState,
    bump_stop_state,
    spring_state,
)
from .springs import (
    lower_arm_motion_ratio_at_pose,
    lower_arm_spring_length,
    ride_frequency_hz,
    ride_rate,
    spring_wheel_support,
    sprung_mass_per_corner,
    wheel_rate,
)
from .sweep import LimitedSweep, limited_sweep


@dataclass(frozen=True)
class SpringMetrics:
    """Сила и локальная жёсткость пружины на нижнем рычаге.

    wheel_support_n — знаковая эквивалентная вертикальная сила на колесе,
    не измеренная реакция шины. None означает отсутствие данных.
    """

    motion_ratio: float
    state: SpringState | None
    wheel_rate_n_mm: float | None
    ride_rate_n_mm: float | None
    frequency_hz: float | None
    error: str | None = None
    wheel_support_n: float | None = None


@dataclass(frozen=True)
class CornerSample:
    """Доступные вычисленные величины для одного достигнутого хода."""

    pose: Pose
    geometry: CornerMetrics
    derivatives: CornerDerivatives
    spring: SpringMetrics | None
    halfshaft: HalfshaftMetrics | None
    halfshaft_violations: tuple[HalfshaftViolation, ...]
    side_metrics: SideMetrics | None
    side_error: str | None
    bump_stop: BumpStopState | None = None
    total_support_n: float | None = None


@dataclass(frozen=True)
class CornerAnalysis:
    """Результат свипа без скрытого заполнения отсутствующих величин."""

    sweep: LimitedSweep
    samples: tuple[CornerSample | None, ...]
    limitations: tuple[str, ...]


def analyze_corner(
    axle: Axle,
    vehicle: Vehicle,
    travels_mm: list[float],
    *,
    side: Literal["left", "right"] = "left",
    spring_mount: Literal["lower_arm"] | None = None,
    coil_bind_length_mm: float | None = None,
    static_spring_length_mm: float | None = None,
    bump_stop: BumpStopCharacteristic | None = None,
    halfshaft: HalfshaftGeometry | None = None,
    halfshaft_limits: HalfshaftLimits | None = None,
    longitudinal_scenario: LongitudinalScenario | None = None,
    max_step_mm: float = 2.0,
) -> CornerAnalysis:
    """Частичный расчёт хода колеса; неприменимые результаты возвращаются как None.

    Развал берётся из настройки оси, суммарное схождение делится поровну
    между сторонами. Пружина рассчитывается только при явном указании
    крепления на нижний рычаг. Рабочую длину самой пружины в статике нужно
    указать отдельно: её изменение предполагается равным изменению расстояния
    опор. Без длины доступна лишь условная оценка линейной жёсткости для
    сжатой пружины. Преднатяг из проекта автоматически не применяется.
    Отбойник рассчитывается только по явно переданным параметрам. При его
    контакте частота не выдаётся; жёсткости spring относятся только к пружине.
    Равновесие не проверяется. Рейка неподвижна.
    """
    model = DoubleWishbone(axle, side)
    limits = ["fixed_rack", "contact_patch_approximation", "caster_from_geometry"]
    if longitudinal_scenario is None:
        limits.append("longitudinal_scenario_unspecified")
    if bump_stop is None:
        limits.append("bump_stop_not_modeled")
    else:
        limits.extend(("bump_stop_constant_motion_ratio", "spring_frequency_excludes_bump_stop"))
        if bump_stop.max_compression_mm is None:
            limits.append("bump_stop_max_compression_unspecified")
    if spring_mount not in (None, "lower_arm"):
        raise ValueError("Неизвестный вариант крепления пружины")
    if spring_mount is None:
        limits.append("spring_mount_unspecified")
    if spring_mount is None and (coil_bind_length_mm is not None or static_spring_length_mm is not None):
        raise ValueError("Для расчёта пружины требуется указать её крепление")
    if static_spring_length_mm is not None and (not isfinite(static_spring_length_mm) or static_spring_length_mm <= 0):
        raise ValueError("Статическая длина пружины должна быть положительной и конечной")
    if coil_bind_length_mm is not None and static_spring_length_mm is None:
        raise ValueError("Для проверки смыкания нужна статическая длина пружины")
    if spring_mount is not None:
        limits.extend(("spring_preload_not_applied", "spring_geometric_stiffness_not_modeled",
                       "spring_equilibrium_not_checked"))
        if static_spring_length_mm is None:
            limits.append("spring_installed_length_unspecified")
            if not axle.spring.progressive:
                limits.append("spring_linear_rate_assumes_loaded")
        else:
            limits.append("spring_length_change_equals_mount_distance_change")
        if coil_bind_length_mm is None:
            limits.append("spring_coil_bind_unspecified")
    if axle.drivetrain.driven and halfshaft is None:
        limits.append("halfshaft_axes_and_plunge_unspecified")
    if not axle.drivetrain.driven and halfshaft is not None:
        raise ValueError("Для неприводной оси нельзя задать полуось")
    if halfshaft_limits is not None and halfshaft is None:
        raise ValueError("Для проверки ШРУСов необходимо задать геометрию полуоси")
    if halfshaft is not None and halfshaft_limits is None:
        limits.append("halfshaft_limits_unspecified")
    lower = upper = None
    characteristic = None
    initial_mount_length = 0.0
    mass = 0.0
    if spring_mount is not None:
        characteristic = SpringCharacteristic(
            free_length_mm=axle.spring.free_len_mm,
            linear_rate_n_mm=axle.spring.rate_N_mm,
            progressive=tuple(axle.spring.progressive),
            coil_bind_length_mm=coil_bind_length_mm,
        )
        try:
            p, q = axle.hardpoints["spring_lo"], axle.hardpoints["spring_up"]
        except KeyError as exc:
            raise ValueError("Не заданы опоры пружины") from exc
        lower = np.array([p.x, p.y * model.sign, p.z], dtype=float)
        upper = np.array([q.x, q.y * model.sign, q.z], dtype=float)
        if not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper)):
            raise ValueError("Координаты опор пружины должны быть конечными")
        initial_mount_length = lower_arm_spring_length(model, model.initial_pose(), lower, upper)
        if initial_mount_length <= 1e-9:
            raise ValueError("Опоры пружины совпадают")
        fraction = vehicle.front_weight_pct / 100 if axle.role == "front" else 1 - vehicle.front_weight_pct / 100
        unsprung = vehicle.unsprung_front_kg if axle.role == "front" else vehicle.unsprung_rear_kg
        mass = sprung_mass_per_corner(vehicle.mass_kg, fraction, unsprung)
    sweep = limited_sweep(model, travels_mm, max_step_mm)
    samples: list[CornerSample | None] = []
    for point in sweep.points:
        if point.pose is None:
            samples.append(None)
            continue
        pose = point.pose
        geometry = corner_metrics(model, pose, static_camber_deg=axle.setup.camber_deg, static_toe_deg=axle.setup.toe_deg_total / 2)
        derivatives = corner_derivatives(model, pose, static_camber_deg=axle.setup.camber_deg, static_toe_deg=axle.setup.toe_deg_total / 2)
        bump = bump_stop_state(bump_stop, pose.travel_mm) if bump_stop is not None else None
        spring = None
        if lower is not None and upper is not None and characteristic is not None:
            ratio = lower_arm_motion_ratio_at_pose(model, pose, lower, upper)
            length = lower_arm_spring_length(model, pose, lower, upper)
            state = None
            error = None
            rate = None
            if static_spring_length_mm is not None:
                spring_length = static_spring_length_mm + (length - initial_mount_length)
                if spring_length <= 0:
                    error = "Расчётная длина пружины неположительна; положение физически недопустимо"
                else:
                    state = spring_state(characteristic, spring_length)
                    rate = state.tangent_rate_n_mm
            elif not characteristic.progressive:
                rate = characteristic.linear_rate_n_mm  # Только при контакте и до смыкания.
            wheel = ride = frequency = None
            if rate is not None:
                wheel = wheel_rate(rate, ratio)
                ride = ride_rate(wheel, axle.wheel.k_tire_N_mm)
                # Нулевая жёсткость не является частотой колебательного равновесия.
                if ride > 0 and (bump is None or bump.status == "clear"):
                    frequency = ride_frequency_hz(ride, mass)
            support = spring_wheel_support(state.force_n, ratio) if state is not None and state.force_n is not None else None
            spring = SpringMetrics(ratio, state, wheel, ride, frequency, error, support)
        drive = halfshaft_metrics(model, pose, halfshaft) if halfshaft is not None else None
        violations = check_halfshaft(drive, halfshaft_limits, pose.travel_mm) if drive is not None and halfshaft_limits is not None else ()
        side_metrics = None
        side_error = None
        if longitudinal_scenario is not None:
            try:
                side_metrics = evaluate_side_scenario(
                    model, pose, longitudinal_scenario,
                    wheelbase_mm=vehicle.wheelbase_mm, cg_height_mm=vehicle.cg_height_mm,
                )
            except (KinematicsError, ValueError) as exc:
                side_error = str(exc)
        total_support = None
        if spring is not None and spring.wheel_support_n is not None and bump is not None and bump.wheel_force_n is not None:
            total_support = spring.wheel_support_n + bump.wheel_force_n
            if not isfinite(total_support):
                total_support = None
        samples.append(CornerSample(pose, geometry, derivatives, spring, drive, violations, side_metrics, side_error,
                                    bump, total_support))
    return CornerAnalysis(sweep, tuple(samples), tuple(limits))
