"""Ход между опорами и проверка явно заданных механических пределов."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np

from .double_wishbone import DoubleWishbone
from .springs import lower_arm_spring_length

Vector3 = tuple[float, float, float]


@dataclass(frozen=True)
class StrokeLimits:
    """Минимальная и максимальная длина элемента между осями креплений."""

    compressed_mm: float
    extended_mm: float

    def __post_init__(self) -> None:
        if not all(isfinite(v) for v in (self.compressed_mm, self.extended_mm)):
            raise ValueError("Границы хода должны быть конечными")
        if self.compressed_mm <= 0 or self.extended_mm <= self.compressed_mm:
            raise ValueError("Длина сжатого элемента должна быть положительна и меньше разжатой")


@dataclass(frozen=True)
class StrokeState:
    """Зазоры до сжатого и разжатого упоров; отрицательный означает конфликт."""

    length_mm: float
    compression_clearance_mm: float
    extension_clearance_mm: float
    status: Literal["inside", "compressed_limit", "extended_limit", "below_compressed", "above_extended"]


def stroke_state(length_mm: float, limits: StrokeLimits) -> StrokeState:
    """Оценивает положение относительно обоих упоров без экстраполяции."""
    if not isfinite(length_mm) or length_mm <= 0:
        raise ValueError("Длина элемента должна быть положительной и конечной")
    compression = length_mm - limits.compressed_mm
    extension = limits.extended_mm - length_mm
    if compression < 0:
        status: Literal["inside", "compressed_limit", "extended_limit", "below_compressed", "above_extended"] = "below_compressed"
    elif extension < 0:
        status = "above_extended"
    elif compression == 0:
        status = "compressed_limit"
    elif extension == 0:
        status = "extended_limit"
    else:
        status = "inside"
    return StrokeState(length_mm, compression, extension, status)


@dataclass(frozen=True)
class StrokeCrossing:
    """Интервал хода колеса, содержащий переход через заданную длину элемента."""

    from_travel_mm: float
    to_travel_mm: float
    from_length_mm: float
    to_length_mm: float
    estimated_travel_mm: float
    evaluations: int


def locate_lower_arm_length(
    model: DoubleWishbone,
    lower: Vector3,
    upper: Vector3,
    target_length_mm: float,
    from_travel_mm: float,
    to_travel_mm: float,
    *,
    travel_tolerance_mm: float = 0.01,
    max_step_mm: float = 2.0,
) -> StrokeCrossing:
    """Уточняет попадание в упор при указанном интервале и креплении.

    Нижняя опора жёстко прикреплена к нижнему рычагу, верхняя — к кузову;
    координаты относятся к выбранной стороне в системе ISO. Решатель
    продолжает статическую ветвь, а при обнаружении ошибки прекращает поиск.
    """
    if not all(isfinite(v) for v in (*lower, *upper, target_length_mm, from_travel_mm,
                                      to_travel_mm, travel_tolerance_mm, max_step_mm)):
        raise ValueError("Координаты, длины и допуски должны быть конечными")
    if len(lower) != 3 or len(upper) != 3:
        raise ValueError("Опоры должны иметь по три координаты")
    if target_length_mm <= 0 or from_travel_mm >= to_travel_mm or travel_tolerance_mm <= 0 or max_step_mm <= 0:
        raise ValueError("Границы должны возрастать, длина, допуск и шаг — быть положительными")
    a = np.array(lower, dtype=float)
    b = np.array(upper, dtype=float)
    low, high = from_travel_mm, to_travel_mm
    left, right = model.sweep([low, high], max_step_mm=max_step_mm)
    low_length = lower_arm_spring_length(model, left, a, b)
    high_length = lower_arm_spring_length(model, right, a, b)
    count = 2
    low_residual, high_residual = low_length - target_length_mm, high_length - target_length_mm
    if low_residual == 0:
        return StrokeCrossing(low, low, low_length, low_length, low, count)
    if high_residual == 0:
        return StrokeCrossing(high, high, high_length, high_length, high, count)
    if (low_residual > 0) == (high_residual > 0):
        raise ValueError("Длины на границах интервала должны лежать по разные стороны от предела")
    for _ in range(80):
        if high - low <= travel_tolerance_mm:
            break
        middle = low + (high - low) / 2
        if middle in (low, high):
            break
        pose = model.solve(middle, max_step_mm=max_step_mm)
        length = lower_arm_spring_length(model, pose, a, b)
        count += 1
        residual = length - target_length_mm
        if residual == 0:
            return StrokeCrossing(middle, middle, length, length, middle, count)
        if (residual > 0) == (low_residual > 0):
            low, low_length, low_residual = middle, length, residual
        else:
            high, high_length = middle, length
    if high - low > travel_tolerance_mm:
        raise ValueError("Не удалось уточнить ход до заданного допуска")
    return StrokeCrossing(low, high, low_length, high_length, low + (high - low) / 2, count)
