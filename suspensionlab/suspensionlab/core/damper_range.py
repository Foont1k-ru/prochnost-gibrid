"""Дискретная сводка геометрической длины для подбора амортизатора."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .stroke import StrokeLimits, stroke_state


@dataclass(frozen=True)
class LengthPoint:
    """Расчётная длина и положение в исходной таблице."""

    row: int
    travel_mm: float
    length_mm: float


@dataclass(frozen=True)
class DamperRange:
    """Крайние значения только на заданных точках, включая положения за упорами."""

    total: int
    missing: int
    shortest: LengthPoint | None
    longest: LengthPoint | None
    compression_clearance_mm: float | None
    extension_clearance_mm: float | None
    conflicts: int | None


def summarize_damper_range(points: list[tuple[float, float | None]],
                           limits: StrokeLimits | None = None) -> DamperRange:
    """Недоступные точки не подставляются; нулевой запас считается упором.

    При одинаковых крайних значениях сохраняется первая строка. Результат не
    проверяет интервалы между точками, допустимость конструкции или силы.
    """
    available: list[LengthPoint] = []
    for row, (travel, length) in enumerate(points):
        if not isfinite(travel):
            raise ValueError("Ход колеса должен быть конечным")
        if length is None:
            continue
        if not isfinite(length) or length <= 0:
            raise ValueError("Расчётная длина должна быть положительной и конечной")
        available.append(LengthPoint(row, travel, length))
    if not available:
        return DamperRange(len(points), len(points), None, None, None, None, None if limits is None else 0)
    shortest = min(available, key=lambda p: p.length_mm)
    longest = max(available, key=lambda p: p.length_mm)
    if limits is None:
        return DamperRange(len(points), len(points) - len(available), shortest, longest, None, None, None)
    conflicts = sum(stroke_state(p.length_mm, limits).status != "inside" for p in available)
    return DamperRange(len(points), len(points) - len(available), shortest, longest,
                       shortest.length_mm - limits.compressed_mm, limits.extended_mm - longest.length_mm, conflicts)
