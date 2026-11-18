"""Кинематика амортизатора с нижним креплением на А-рычаге."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model.entities import Axle
from .double_wishbone import DoubleWishbone, Pose
from .springs import lower_arm_motion_ratio_at_pose, lower_arm_spring_length
from .stroke import StrokeLimits, StrokeState, stroke_state


@dataclass(frozen=True)
class DamperMetrics:
    """Изменение длины и запасы амортизатора; неизвестные упоры не проверены."""

    length_mm: float
    compression_from_static_mm: float
    motion_ratio: float | None
    stroke: StrokeState | None
    error: str | None = None

    @property
    def has_detected_conflict(self) -> bool:
        """Состояние на известном упоре или за ним, либо совпадение опор."""
        return self.error is not None or (self.stroke is not None and self.stroke.status != "inside")


class LowerArmDamper:
    """Нижняя опора на рычаге, верхняя на кузове, координаты оси зеркалируются."""

    def __init__(self, model: DoubleWishbone, axle: Axle) -> None:
        self.model = model
        try:
            p, q = axle.hardpoints["damper_lo"], axle.hardpoints["damper_up"]
        except KeyError as exc:
            raise ValueError("Не заданы опоры амортизатора") from exc
        self.lower = np.array([p.x, p.y * model.sign, p.z], dtype=float)
        self.upper = np.array([q.x, q.y * model.sign, q.z], dtype=float)
        if not np.all(np.isfinite(self.lower)) or not np.all(np.isfinite(self.upper)):
            raise ValueError("Координаты опор амортизатора должны быть конечными")
        self.initial_length_mm = lower_arm_spring_length(model, model.initial_pose(), self.lower, self.upper)
        if self.initial_length_mm <= 1e-9:
            raise ValueError("Опоры амортизатора совпадают")

    def evaluate(self, pose: Pose, limits: StrokeLimits | None = None) -> DamperMetrics:
        """Проверяет только переданное положение; геометрический ход не ограничивает."""
        length = lower_arm_spring_length(self.model, pose, self.lower, self.upper)
        compression = self.initial_length_mm - length
        if length <= 1e-9:
            return DamperMetrics(length, compression, None, None, "Опоры амортизатора совпадают")
        ratio = lower_arm_motion_ratio_at_pose(self.model, pose, self.lower, self.upper)
        stroke = stroke_state(length, limits) if limits is not None else None
        return DamperMetrics(length, compression, ratio, stroke)


def linear_coefficient_from_point(force_n: float, speed_mm_s: float) -> float:
    """Условная прямая через начало координат по модулю силы и скорости штока.

    Одна точка не определяет форму кривой, трение, гистерезис или газовое усилие.
    Это не измерение демпфирующего коэффициента для всего диапазона скоростей.
    """
    from math import isfinite

    if not isfinite(force_n) or force_n < 0 or not isfinite(speed_mm_s) or speed_mm_s <= 0:
        raise ValueError("Нужны неотрицательная сила и положительная скорость штока, конечные числа")
    coefficient = force_n / speed_mm_s
    if not isfinite(coefficient) or (force_n > 0 and coefficient == 0):
        raise ValueError("Коэффициент невозможно представить с доступной точностью")
    return coefficient


@dataclass(frozen=True)
class DamperForcePoint:
    """Исходная пара для условной линейной оценки, а не полная характеристика."""

    force_n: float
    speed_mm_s: float

    def __post_init__(self) -> None:
        linear_coefficient_from_point(self.force_n, self.speed_mm_s)

    @property
    def coefficient_n_s_mm(self) -> float:
        return linear_coefficient_from_point(self.force_n, self.speed_mm_s)


@dataclass(frozen=True)
class LinearDamperCharacteristic:
    """Условные коэффициенты сжатия и отбоя, Н·с/мм; задаются явно.

    Не описывает сухое трение, газовое усилие, гистерезис и нелинейные клапаны.
    """

    compression_n_s_per_mm: float
    rebound_n_s_per_mm: float

    def __post_init__(self) -> None:
        from math import isfinite

        values = (self.compression_n_s_per_mm, self.rebound_n_s_per_mm)
        if not all(isfinite(value) and value >= 0 for value in values):
            raise ValueError("Коэффициенты демпфирования должны быть конечными и неотрицательными")


@dataclass(frozen=True)
class DamperDynamics:
    """Скорости сжатия и силы с выбранными знаками; диссипация в ваттах."""

    wheel_velocity_mm_s: float
    compression_velocity_mm_s: float
    resistance_n: float
    wheel_force_n: float
    dissipated_power_w: float
    stroke_limits_checked: bool


def evaluate_linear_damping(
    metrics: DamperMetrics,
    characteristic: LinearDamperCharacteristic,
    wheel_velocity_mm_s: float,
) -> DamperDynamics:
    """Оценка демпфирования для заданной мгновенной скорости колеса.

    Ход и скорость колеса положительны вверх. Скорость сжатия амортизатора
    равна MR * скорость колеса; сопротивление на элементе имеет тот же знак,
    что скорость сжатия. Сила на колесе противоположна его скорости, а
    положительная мощность — энергия, рассеиваемая в виде тепла. Результат
    не включает упоры и не добавляется в баланс сил автоматически.
    """
    from math import isfinite

    if not isfinite(wheel_velocity_mm_s):
        raise ValueError("Скорость колеса должна быть конечной")
    if metrics.has_detected_conflict:
        raise ValueError("Демпфирование не определяется на упоре или при ошибке геометрии")
    if (not isfinite(metrics.length_mm) or metrics.length_mm <= 0
            or not isfinite(metrics.compression_from_static_mm)):
        raise ValueError("Длина и сжатие амортизатора должны быть корректными")
    if metrics.stroke is not None and (
        metrics.stroke.length_mm != metrics.length_mm
        or not all(isfinite(v) and v > 0 for v in (
            metrics.stroke.compression_clearance_mm, metrics.stroke.extension_clearance_mm
        ))
    ):
        raise ValueError("Некорректные данные проверки упоров амортизатора")
    if metrics.motion_ratio is None or not isfinite(metrics.motion_ratio):
        raise ValueError("Передаточное отношение амортизатора не определено")
    velocity = metrics.motion_ratio * wheel_velocity_mm_s
    coefficient = characteristic.compression_n_s_per_mm if velocity >= 0 else characteristic.rebound_n_s_per_mm
    resistance = coefficient * velocity
    wheel_force = -resistance * metrics.motion_ratio
    power = resistance * velocity / 1000.0
    if not all(isfinite(value) for value in (velocity, resistance, wheel_force, power)):
        raise ValueError("Результат демпфирования не является конечным")
    return DamperDynamics(wheel_velocity_mm_s, velocity, resistance, wheel_force, power, metrics.stroke is not None)
