"""Предварительная сводка состояний одной пружины по рассчитанным точкам."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .damper_range import LengthPoint
from .spring_characteristics import SpringState


@dataclass(frozen=True)
class SpringRange:
    """Сводка исходной пружины, не проверка всей конструкции или подбор изделия."""

    total: int
    missing: int
    shortest: LengthPoint | None
    longest: LengthPoint | None
    free_length_mm: float
    coil_bind_length_mm: float | None
    min_coil_clearance_mm: float | None
    coil_bind_count: int | None
    free_boundary_count: int
    slack_count: int
    force_missing_count: int
    first_free: LengthPoint | None


def summarize_spring_range(
    points: list[tuple[float, SpringState | None]], free_length_mm: float, coil_bind_length_mm: float | None,
) -> SpringRange:
    """Состояния без интерполяции; при равенстве длины первая строка.

    Свободная длина — порог отсутствия сжатия, не предел хода подвески.
    Смыкание включается только с заданной длиной; ошибки и пропуски не нули.
    """
    if not isfinite(free_length_mm) or free_length_mm <= 0:
        raise ValueError("Свободная длина должна быть положительной и конечной")
    if coil_bind_length_mm is not None and (not isfinite(coil_bind_length_mm)
                                             or not 0 < coil_bind_length_mm < free_length_mm):
        raise ValueError("Длина смыкания должна быть положительной и меньше свободной")
    available: list[tuple[LengthPoint, SpringState]] = []
    for row, (travel, state) in enumerate(points):
        if not isfinite(travel):
            raise ValueError("Ход должен быть конечным")
        if state is None:
            continue
        length = state.length_mm
        if not isfinite(length) or length <= 0:
            raise ValueError("Длина пружины должна быть положительной и конечной")
        expected_clearance = None if coil_bind_length_mm is None else length - coil_bind_length_mm
        if state.coil_clearance_mm != expected_clearance:
            raise ValueError("Состояние пружины не соответствует заданной длине смыкания")
        if (state.status == "coil_bind") != (expected_clearance is not None and expected_clearance <= 0):
            raise ValueError("Несогласованное состояние смыкания пружины")
        if (state.status == "slack") != (length > free_length_mm):
            raise ValueError("Несогласованное состояние свободной пружины")
        if (state.status == "free_boundary") != (length == free_length_mm):
            raise ValueError("Несогласованное состояние свободной длины")
        available.append((LengthPoint(row, travel, length), state))
    shortest = min((p for p, _ in available), key=lambda p: p.length_mm, default=None)
    longest = max((p for p, _ in available), key=lambda p: p.length_mm, default=None)
    at_free = [p for p, state in available if state.status in ("slack", "free_boundary")]
    return SpringRange(
        len(points), len(points) - len(available), shortest, longest, free_length_mm, coil_bind_length_mm,
        shortest.length_mm - coil_bind_length_mm if shortest is not None and coil_bind_length_mm is not None else None,
        sum(state.status == "coil_bind" for _, state in available) if coil_bind_length_mm is not None else None,
        sum(state.status == "free_boundary" for _, state in available),
        sum(state.status == "slack" for _, state in available),
        sum(state.force_n is None or not isfinite(state.force_n) for _, state in available), at_free[0] if at_free else None,
    )
