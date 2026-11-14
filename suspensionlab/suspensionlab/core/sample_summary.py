"""Сводка дискретных проверок; промежутки между точками не исследуются."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from .analysis import CornerAnalysis, CornerSample
from .antiroll import AntiRollPoint
from .combined_checks import ComponentChecks

SampleStatus = Literal["unavailable", "conflict", "incomplete", "checked"]
_STATUSES = {"unavailable", "conflict", "incomplete", "checked"}


@dataclass(frozen=True)
class SampleCheck:
    travel_mm: float
    status: SampleStatus
    right_travel_mm: float | None = None


@dataclass(frozen=True)
class SampleGroup:
    """Последовательные записи одного статуса; не непрерывный интервал хода."""

    first_row: int
    last_row: int
    first: SampleCheck
    last: SampleCheck

    @property
    def count(self) -> int:
        return self.last_row - self.first_row + 1


def corner_status(sample: CornerSample | None) -> SampleStatus:
    """Проверяет только известные смыкание пружины и длины упоров амортизатора."""
    if sample is None:
        return "unavailable"
    spring, damper = sample.spring, sample.damper
    state = spring.state if spring is not None else None
    if (spring is not None and (spring.error is not None or (state is not None and state.status == "coil_bind"))
            or damper is not None and damper.has_detected_conflict):
        return "conflict"
    if (state is None or state.coil_clearance_mm is None or state.force_n is None
            or damper is None or damper.stroke is None):
        return "incomplete"
    return "checked"


def corner_summary(analysis: CornerAnalysis) -> tuple[SampleCheck, ...]:
    return tuple(SampleCheck(point.travel_mm, corner_status(sample))
                 for point, sample in zip(analysis.sweep.points, analysis.samples, strict=True))


def antiroll_status(point: AntiRollPoint, pair: tuple[ComponentChecks, ComponentChecks] | None) -> SampleStatus:
    """Обе стороны; неназначенные или недоступные проверки не считаются успешными."""
    if point.state is None:
        return "unavailable"
    if pair is None:
        return "incomplete"
    for check in pair:
        if (check.spring is not None and check.spring.status in ("invalid", "coil_bind")):
            return "conflict"
        if check.damper is not None and (check.damper.invalid or
                (check.damper.stroke is not None and check.damper.stroke.status != "inside")):
            return "conflict"
    for check in pair:
        if (check.spring is None or check.spring.status != "clear" or check.damper is None
                or check.damper.stroke is None):
            return "incomplete"
    return "checked"


def antiroll_summary(points: tuple[AntiRollPoint, ...],
                     checks: list[tuple[ComponentChecks, ComponentChecks] | None]) -> tuple[SampleCheck, ...]:
    return tuple(SampleCheck(point.left_travel_mm, antiroll_status(point, pair), point.right_travel_mm)
                 for point, pair in zip(points, checks, strict=True))


def group_samples(samples: tuple[SampleCheck, ...]) -> tuple[SampleGroup, ...]:
    """Группирует только соседние строки одного статуса; порядок исходных строк не меняется."""
    if any(s.status not in _STATUSES or not isfinite(s.travel_mm)
           or (s.right_travel_mm is not None and not isfinite(s.right_travel_mm)) for s in samples):
        raise ValueError("Некорректные данные сводки")
    groups: list[SampleGroup] = []
    start = 0
    for i in range(1, len(samples) + 1):
        if i == len(samples) or samples[i].status != samples[start].status:
            groups.append(SampleGroup(start, i - 1, samples[start], samples[i - 1]))
            start = i
    return tuple(groups)
