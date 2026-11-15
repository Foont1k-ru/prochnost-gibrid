"""Дискретная сводка геометрической длины для подбора амортизатора."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from .stroke import StrokeLimits, StrokeState, stroke_state


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


@dataclass(frozen=True)
class CandidatePoint:
    """Статус одной исходной строки; недоступная длина не заменяется нулём."""

    travel_mm: float
    length_mm: float | None
    stroke: StrokeState | None
    status: Literal["missing", "stop", "reserve_short", "clear"]


@dataclass(frozen=True)
class CandidateComparison:
    """Проверка альтернативных упоров по тем же точкам, без пересчёта поз."""

    summary: DamperRange
    reserve_mm: float
    insufficient_reserve: int
    first_stop: LengthPoint | None
    first_insufficient: LengthPoint | None
    points: tuple[CandidatePoint, ...]


def compare_candidate(points: list[tuple[float, float | None]], limits: StrokeLimits,
                      reserve_mm: float) -> CandidateComparison:
    """Считает упоры и отдельно точки внутри упоров с запасом меньше заданного.

    Запас ровно равный положительному требованию достаточен. При нулевом
    требовании точка на упоре всё равно считается конфликтом. Статус определяется
    по исходным числам, не по округлённым значениям в интерфейсе.
    """
    if not isfinite(reserve_mm) or reserve_mm < 0:
        raise ValueError("Запас должен быть конечным и неотрицательным")
    summary = summarize_damper_range(points, limits)
    insufficient: list[LengthPoint] = []
    stopped: list[LengthPoint] = []
    results: list[CandidatePoint] = []
    for row, (travel, length) in enumerate(points):
        if length is None:
            results.append(CandidatePoint(travel, None, None, "missing"))
            continue
        state = stroke_state(length, limits)
        point = LengthPoint(row, travel, length)
        if state.status != "inside":
            status: Literal["missing", "stop", "reserve_short", "clear"] = "stop"
            stopped.append(point)
        elif min(state.compression_clearance_mm, state.extension_clearance_mm) < reserve_mm:
            status = "reserve_short"
            insufficient.append(point)
        else:
            status = "clear"
        results.append(CandidatePoint(travel, length, state, status))
    return CandidateComparison(summary, reserve_mm, len(insufficient),
                               stopped[0] if stopped else None, insufficient[0] if insufficient else None,
                               tuple(results))
