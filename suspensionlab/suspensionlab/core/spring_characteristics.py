"""Силовая характеристика пружины и идеализированного отбойника.

Функции вычисляют только локальные одномерные характеристики. Зазоры,
перенос сил на колесо и положение упоров требуют отдельно заданных данных.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal


@dataclass(frozen=True)
class SpringCharacteristic:
    """Свободная длина и характеристика силы от сжатия, мм и Н.

    Прогрессивные точки при наличии задаются от (0, 0), сила возрастает.
    Свободная длина относится к несжатой пружине; дополнительные шайбы и
    преднатяг должны быть отражены в фактической установленной длине.
    """

    free_length_mm: float
    linear_rate_n_mm: float
    progressive: tuple[tuple[float, float], ...] = ()
    coil_bind_length_mm: float | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.free_length_mm) or self.free_length_mm <= 0:
            raise ValueError("Свободная длина пружины должна быть положительной и конечной")
        if not isfinite(self.linear_rate_n_mm) or self.linear_rate_n_mm <= 0:
            raise ValueError("Жёсткость пружины должна быть положительной и конечной")
        if self.coil_bind_length_mm is not None and (
            not isfinite(self.coil_bind_length_mm) or not 0 < self.coil_bind_length_mm < self.free_length_mm
        ):
            raise ValueError("Длина смыкания витков должна быть положительна и меньше свободной длины")
        if self.progressive:
            if len(self.progressive) < 2 or self.progressive[0] != (0.0, 0.0):
                raise ValueError("Характеристика должна начинаться точкой нулевого сжатия и силы")
            if any(not isfinite(x) or not isfinite(force) for x, force in self.progressive):
                raise ValueError("Точки характеристики должны быть конечными")
            if any(x1 <= x0 or f1 <= f0 for (x0, f0), (x1, f1) in zip(self.progressive, self.progressive[1:], strict=False)):
                raise ValueError("Сжатие и сила должны строго возрастать")


@dataclass(frozen=True)
class SpringState:
    """Длина, сжатие, сила и локальная жёсткость; None означает неопределённость."""

    length_mm: float
    compression_mm: float
    force_n: float | None
    tangent_rate_n_mm: float | None
    coil_clearance_mm: float | None
    status: Literal["slack", "free_boundary", "loaded", "curve_knot", "outside_curve", "coil_bind"]


def spring_state(characteristic: SpringCharacteristic, length_mm: float) -> SpringState:
    """Определяет усилие по установленной длине без экстраполяции таблицы.

    При смыкании витков, на изломе или границе свободной длины локальная
    жёсткость не определяется. Длина меньше длины смыкания означает, что
    геометрическое положение конфликтует с пружиной, а не реальную силу.
    """
    if not isfinite(length_mm) or length_mm <= 0:
        raise ValueError("Установленная длина пружины должна быть положительной и конечной")
    compression = max(characteristic.free_length_mm - length_mm, 0.0)
    clearance = None if characteristic.coil_bind_length_mm is None else length_mm - characteristic.coil_bind_length_mm
    if clearance is not None and clearance <= 0:
        return SpringState(length_mm, compression, None, None, clearance, "coil_bind")
    if length_mm > characteristic.free_length_mm:
        return SpringState(length_mm, 0.0, 0.0, 0.0, clearance, "slack")
    if length_mm == characteristic.free_length_mm:
        return SpringState(length_mm, 0.0, 0.0, None, clearance, "free_boundary")
    curve = characteristic.progressive
    if not curve:
        return SpringState(length_mm, compression, characteristic.linear_rate_n_mm * compression,
                           characteristic.linear_rate_n_mm, clearance, "loaded")
    for x, force in curve:
        if compression == x:
            return SpringState(length_mm, compression, force, None, clearance, "curve_knot")
    for (x0, f0), (x1, f1) in zip(curve, curve[1:], strict=False):
        if x0 < compression < x1:
            rate = (f1 - f0) / (x1 - x0)
            return SpringState(length_mm, compression, f0 + rate * (compression - x0), rate, clearance, "loaded")
    return SpringState(length_mm, compression, None, None, clearance, "outside_curve")


@dataclass(frozen=True)
class BumpStopCharacteristic:
    """Линейный отбойник при заданных точке вступления и передаточном отношении."""

    engage_travel_mm: float
    rate_n_mm: float
    motion_ratio: float
    max_compression_mm: float | None = None

    def __post_init__(self) -> None:
        if not all(isfinite(v) for v in (self.engage_travel_mm, self.rate_n_mm, self.motion_ratio)):
            raise ValueError("Параметры отбойника должны быть конечными")
        if self.rate_n_mm <= 0 or self.motion_ratio <= 0:
            raise ValueError("Жёсткость и передаточное отношение отбойника должны быть положительными")
        if self.max_compression_mm is not None and (not isfinite(self.max_compression_mm) or self.max_compression_mm <= 0):
            raise ValueError("Предельное сжатие отбойника должно быть положительным")


@dataclass(frozen=True)
class BumpStopState:
    """Ход до начала контакта, сжатие, силы и жёсткость отбойника."""

    remaining_wheel_travel_mm: float
    compression_mm: float
    force_n: float | None
    wheel_force_n: float | None
    wheel_rate_n_mm: float | None
    status: Literal["clear", "contact_boundary", "engaged", "bottomed"]


def bump_stop_state(characteristic: BumpStopCharacteristic, wheel_travel_mm: float) -> BumpStopState:
    """Линейный контакт при постоянном заданном передаточном отношении."""
    if not isfinite(wheel_travel_mm):
        raise ValueError("Ход колеса должен быть конечным")
    delta = wheel_travel_mm - characteristic.engage_travel_mm
    compression = max(0.0, delta * characteristic.motion_ratio)
    remaining = characteristic.engage_travel_mm - wheel_travel_mm
    if not all(isfinite(v) for v in (delta, compression, remaining)):
        raise ValueError("Ход или сжатие отбойника не являются конечными")
    if characteristic.max_compression_mm is not None and compression >= characteristic.max_compression_mm:
        return BumpStopState(remaining, compression, None, None, None, "bottomed")
    if delta < 0:
        return BumpStopState(remaining, compression, 0.0, 0.0, 0.0, "clear")
    if delta == 0:
        return BumpStopState(remaining, compression, 0.0, 0.0, None, "contact_boundary")
    force = characteristic.rate_n_mm * compression
    wheel_force = force * characteristic.motion_ratio
    wheel_stiffness = characteristic.rate_n_mm * characteristic.motion_ratio * characteristic.motion_ratio
    if not all(isfinite(v) for v in (force, wheel_force, wheel_stiffness)):
        raise ValueError("Сила или жёсткость отбойника не являются конечными")
    return BumpStopState(remaining, compression, force, wheel_force, wheel_stiffness, "engaged")
