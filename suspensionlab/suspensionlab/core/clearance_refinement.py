"""Ограниченное адаптивное добавление дискретных положений проверки зазоров."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import inf, isfinite

from ..model.entities import Axle
from .suspension_clearance import ClearanceSample, ClearanceSweep, calculate_link_clearance

MAX_EXTRA = 120
MAX_ROUNDS = 3


@dataclass(frozen=True, slots=True)
class RefinementInterval:
    start_mm: float
    end_mm: float
    reason: str
    minimum_clearance_mm: float | None


@dataclass(frozen=True, slots=True)
class RefinementReport:
    sweep: ClearanceSweep
    initial_travels: tuple[float, ...]
    added: int
    rounds: int
    unresolved: tuple[RefinementInterval, ...]
    unprobed_initial: tuple[tuple[float, float], ...]
    inaccessible: tuple[tuple[float, float], ...]
    limited_by_budget: bool
    limited_by_rounds: bool
    limited_by_spacing: bool


def _candidate(a: ClearanceSample, b: ClearanceSample, threshold: float) -> RefinementInterval | None:
    if not a.pose_available and not b.pose_available:
        return None  # Continued failures are not extrapolated.
    boundary = a.pose_available != b.pose_available
    low: list[float] = []
    for left, right in zip(a.pairs, b.pairs, strict=True):
        if (left.first, left.second) != (right.first, right.second):
            raise ValueError('Несовместимые пары на соседних позициях')
        if ((left.measurement is not None and right.status in ('unknown_geometry', 'unknown_no_pose')) or
                (right.measurement is not None and left.status in ('unknown_geometry', 'unknown_no_pose'))):
            boundary = True
        low.extend(p.measurement.clearance_mm for p in (left, right) if p.measurement is not None)
    minimum = min(low) if low else None
    if boundary:
        return RefinementInterval(a.travel_mm, b.travel_mm, 'граница доступного расчёта', minimum)
    if minimum is not None and minimum <= threshold:
        return RefinementInterval(a.travel_mm, b.travel_mm, 'малый зазор или наложение', minimum)
    return None


def _can_split(a: float, b: float, min_spacing_mm: float) -> bool:
    midpoint = (a + b) / 2
    return midpoint > a and midpoint < b and (b - a) / 2 >= min_spacing_mm - 1e-12


def refine_link_clearance(axle: Axle, start_mm: float, end_mm: float, spacing_mm: float,
                          radii_mm: Mapping[str, float], required_clearance_mm: float, *,
                          wheel_width_mm: float | None = None, alert_band_mm: float = 5.,
                          min_spacing_mm: float = .5, max_extra: int = MAX_EXTRA,
                          max_rounds: int = MAX_ROUNDS) -> RefinementReport:
    """Сначала середины исходных интервалов, затем опасные интервалы.

    Порог опасности = заданный запас + зона внимания. Переход от доступного
    результата к отказу имеет приоритет. Каждая итерация заново рассчитывает
    всю объединённую сетку от нуля; результаты разных проходов не смешиваются.
    Начальная сетка до 61 точки, максимум 120 дополнительных точек и 3 прохода.
    Середина не рассчитывается между двумя неуспешными позами или если половина
    интервала меньше min_spacing_mm. При исчерпании бюджета остаётся явный отчёт.
    Ни эта эвристика, ни заданная точность не доказывают непрерывного зазора.
    """
    if (type(alert_band_mm) not in (int, float) or not isfinite(alert_band_mm) or
            not 0 <= alert_band_mm <= 1_000_000):
        raise ValueError('Зона внимания должна быть конечной и неотрицательной')
    if (type(min_spacing_mm) not in (int, float) or not isfinite(min_spacing_mm) or
            not .1 <= min_spacing_mm <= 30):
        raise ValueError('Минимальный интервал должен быть от 0,1 до 30 мм')
    if type(max_extra) is not int or not 0 <= max_extra <= MAX_EXTRA:
        raise ValueError('Некорректный бюджет дополнительных точек')
    if type(max_rounds) is not int or not 0 <= max_rounds <= MAX_ROUNDS:
        raise ValueError('Некорректное число проходов')
    sweep = calculate_link_clearance(axle, start_mm, end_mm, spacing_mm, radii_mm, required_clearance_mm,
                                     wheel_width_mm=wheel_width_mm)
    initial = tuple(s.travel_mm for s in sweep.samples)
    initial_pairs = list(zip(sweep.samples, sweep.samples[1:], strict=False))
    attempted: set[tuple[float, float]] = set()
    added = rounds = 0
    budget_hit = False
    for stage in range(max_rounds):
        if stage == 0:
            candidates = [RefinementInterval(a.travel_mm, b.travel_mm, 'середина исходного интервала', None)
                          for a, b in initial_pairs if a.pose_available or b.pose_available]
        else:
            candidates = [candidate for a, b in zip(sweep.samples, sweep.samples[1:], strict=False)
                          if (candidate := _candidate(a, b, required_clearance_mm + alert_band_mm)) is not None]
            candidates.sort(key=lambda c: (c.reason != 'граница доступного расчёта',
                                            c.minimum_clearance_mm if c.minimum_clearance_mm is not None else inf,
                                            c.start_mm))
        candidates = [c for c in candidates if _can_split(c.start_mm, c.end_mm, min_spacing_mm)]
        remaining = max_extra - added
        if len(candidates) > remaining:
            budget_hit = True
        chosen = candidates[:remaining]
        if not chosen:
            break
        if stage == 0:
            attempted.update((c.start_mm, c.end_mm) for c in chosen)
        targets = sorted({s.travel_mm for s in sweep.samples} |
                         {(c.start_mm + c.end_mm) / 2 for c in chosen})
        added += len(targets) - len(sweep.samples)
        rounds += 1
        sweep = calculate_link_clearance(axle, start_mm, end_mm, spacing_mm, radii_mm, required_clearance_mm,
                                         wheel_width_mm=wheel_width_mm, targets=targets)
    unresolved = tuple(candidate for a, b in zip(sweep.samples, sweep.samples[1:], strict=False)
                       if (candidate := _candidate(a, b, required_clearance_mm + alert_band_mm)) is not None)
    unprobed = tuple((a.travel_mm, b.travel_mm) for a, b in initial_pairs
                     if (a.travel_mm, b.travel_mm) not in attempted)
    inaccessible = tuple((a.travel_mm, b.travel_mm) for a, b in zip(sweep.samples, sweep.samples[1:], strict=False)
                         if not a.pose_available and not b.pose_available)
    splittable = any(_can_split(c.start_mm, c.end_mm, min_spacing_mm) for c in unresolved)
    unprobed_available = [(a.travel_mm, b.travel_mm) for a, b in initial_pairs
                          if (a.pose_available or b.pose_available) and (a.travel_mm, b.travel_mm) not in attempted]
    unprobed_splittable = any(_can_split(a, b, min_spacing_mm) for a, b in unprobed_available)
    spacing_hit = (any(not _can_split(c.start_mm, c.end_mm, min_spacing_mm) for c in unresolved) or
                   any(not _can_split(a, b, min_spacing_mm) for a, b in unprobed_available))
    return RefinementReport(sweep, initial, added, rounds, unresolved, unprobed, inaccessible,
                            budget_hit or (added == max_extra and (splittable or unprobed_splittable)),
                            rounds == max_rounds and (splittable or unprobed_splittable) and added < max_extra,
                            spacing_hit)
