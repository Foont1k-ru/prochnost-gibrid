"""Контроль знака плеча обкатки по дискретному набору ходов."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .double_wishbone import DoubleWishbone


@dataclass(frozen=True)
class SignChange:
    """Интервал разных знаков и линейная оценка положения нуля, мм хода."""

    from_travel_mm: float
    to_travel_mm: float
    from_value_mm: float
    to_value_mm: float
    estimated_zero_mm: float


@dataclass(frozen=True)
class ScrubSignAnalysis:
    """Обнаруженные интервалы смены знака и нулевые точки выборки.

    Отсутствие обнаруженных изменений не доказывает неизменность знака
    между узлами сетки; при пропусках проверка дополнительно неполна.
    """

    changes: tuple[SignChange, ...]
    near_zero_travel_mm: tuple[float, ...]
    missing_travel_mm: tuple[float, ...]
    sample_count: int

    @property
    def complete_samples(self) -> bool:
        """Вычислены ли все переданные точки, без утверждения о промежутках."""
        return self.sample_count > 0 and not self.missing_travel_mm

    @property
    def sign_change_detected(self) -> bool:
        """Обнаружены ли на соседних доступных участках разные знаки."""
        return bool(self.changes)


def check_scrub_signs(
    observations: list[tuple[float, float | None]], *, zero_tolerance_mm: float = 1e-6
) -> ScrubSignAnalysis:
    """Проверяет выборку без интерполяции через недоступные точки.

    Точки в диапазоне ±допуск записываются отдельно. Если по обе стороны
    от таких точек наблюдаются разные знаки, возвращается один интервал;
    оценка нуля внутри него — только линейная интерполяция, не решение.
    """
    if not isfinite(zero_tolerance_mm) or zero_tolerance_mm < 0:
        raise ValueError("Допуск нуля должен быть конечным и неотрицательным")
    values = sorted(observations, key=lambda pair: pair[0])
    if any(not isfinite(travel) or (value is not None and not isfinite(value)) for travel, value in values):
        raise ValueError("Ходы и доступные значения должны быть конечными")
    if any(a[0] == b[0] for a, b in zip(values, values[1:], strict=False)):
        raise ValueError("Ходы в выборке должны быть уникальными")
    previous: tuple[float, float] | None = None
    changes: list[SignChange] = []
    zeros: list[float] = []
    missing: list[float] = []
    for travel, value in values:
        if value is None:
            missing.append(travel)
            previous = None
            continue
        if abs(value) <= zero_tolerance_mm:
            zeros.append(travel)
            continue
        if previous is not None and (value > 0) != (previous[1] > 0):
            x0, y0 = previous
            root = x0 + (travel - x0) * (-y0) / (value - y0)
            changes.append(SignChange(x0, travel, y0, value, root))
        previous = (travel, value)
    return ScrubSignAnalysis(tuple(changes), tuple(zeros), tuple(missing), len(values))


@dataclass(frozen=True)
class RefinedSignChange:
    """Численно уточнённый интервал нуля на одной непрерывной ветви."""

    from_travel_mm: float
    to_travel_mm: float
    from_value_mm: float
    to_value_mm: float
    estimated_zero_mm: float
    evaluations: int


def refine_scrub_sign_change(
    model: DoubleWishbone,
    from_travel_mm: float,
    to_travel_mm: float,
    *,
    travel_tolerance_mm: float = 0.01,
    max_step_mm: float = 2.0,
) -> RefinedSignChange:
    """Уточняет обнаруженный переход делением интервала с пересчётом геометрии.

    Оба края должны давать противоположные знаки либо один — точный ноль.
    Каждая позиция проверяется продолжением от статики. Если промежуточное
    решение не получено, исключение передаётся вызывающему коду; заведомо
    недоступные точки не пропускаются. Отсутствие перехода вне
    переданного интервала этот метод не доказывает.
    """
    from .metrics import corner_metrics

    if not all(isfinite(v) for v in (from_travel_mm, to_travel_mm, travel_tolerance_mm, max_step_mm)):
        raise ValueError("Ход и допуски должны быть конечными")
    if from_travel_mm >= to_travel_mm or travel_tolerance_mm <= 0 or max_step_mm <= 0:
        raise ValueError("Границы должны возрастать, шаг и допуск — быть положительными")
    low, high = from_travel_mm, to_travel_mm
    left_pose, right_pose = model.sweep([low, high], max_step_mm=max_step_mm)
    low_value = corner_metrics(model, left_pose).scrub_radius_mm
    high_value = corner_metrics(model, right_pose).scrub_radius_mm
    evaluations = 2
    if low_value == 0:
        return RefinedSignChange(low, low, low_value, low_value, low, evaluations)
    if high_value == 0:
        return RefinedSignChange(high, high, high_value, high_value, high, evaluations)
    if (low_value > 0) == (high_value > 0):
        raise ValueError("На концах интервала плечо обкатки должно иметь разные знаки")
    for _ in range(80):
        if high - low <= travel_tolerance_mm:
            break
        middle = low + (high - low) / 2
        if middle in (low, high):
            break
        value = corner_metrics(model, model.solve(middle, max_step_mm=max_step_mm)).scrub_radius_mm
        evaluations += 1
        if value == 0:
            return RefinedSignChange(middle, middle, value, value, middle, evaluations)
        if (value > 0) == (low_value > 0):
            low, low_value = middle, value
        else:
            high, high_value = middle, value
    if high - low > travel_tolerance_mm:
        raise ValueError("Не удалось уточнить интервал до заданного допуска")
    return RefinedSignChange(low, high, low_value, high_value, low + (high - low) / 2, evaluations)
