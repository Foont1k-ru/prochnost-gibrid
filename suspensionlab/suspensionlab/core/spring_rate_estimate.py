"""Предварительная секущая жёсткость из двух силовых точек пружины."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class SpringRateEstimate:
    rate_n_mm: float
    extrapolated_zero_length_mm: float
    model_force_1_n: float
    model_force_2_n: float


def estimate_spring_rate(length_1_mm: float, force_1_n: float, length_2_mm: float, force_2_n: float,
                         free_length_mm: float) -> SpringRateEstimate:
    """Секущая dF/dсжатие, без проверки экспериментальных данных.

    Сравнение с текущей моделью F = k * max(Lfree - L, 0) показывает
    несовпадение исходных точек с моделью с нулевой силой на заданной свободной
    длине. Экстраполированная нулевая длина — математический результат, не
    измерение свободной длины и не гарантия линейности вне двух точек.
    """
    values = (length_1_mm, force_1_n, length_2_mm, force_2_n, free_length_mm)
    if not all(isfinite(x) for x in values):
        raise ValueError("Исходные данные должны быть конечными")
    if min(length_1_mm, length_2_mm, free_length_mm) <= 0 or min(force_1_n, force_2_n) < 0:
        raise ValueError("Длины должны быть положительными, силы — неотрицательными")
    delta_length = length_1_mm - length_2_mm
    delta_force = force_2_n - force_1_n
    if delta_length == 0 or delta_force == 0:
        raise ValueError("Точки должны различаться по длине и силе")
    rate = delta_force / delta_length
    if not isfinite(rate) or rate <= 0:
        raise ValueError("При уменьшении длины сила должна увеличиваться; жёсткость должна быть конечной")
    zero_length = length_1_mm + force_1_n / rate
    model_1 = rate * max(free_length_mm - length_1_mm, 0.0)
    model_2 = rate * max(free_length_mm - length_2_mm, 0.0)
    if not all(isfinite(x) for x in (zero_length, model_1, model_2)):
        raise ValueError("Результат нельзя представить с доступной точностью")
    return SpringRateEstimate(rate, zero_length, model_1, model_2)
