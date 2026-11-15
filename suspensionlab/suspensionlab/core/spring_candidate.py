"""Предварительное сравнение длин другой пружины по сохранённой сетке хода."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

CandidateStatus = Literal["missing", "invalid", "coil_bind", "uncompressed", "reserve_short", "clear"]


@dataclass(frozen=True)
class SpringCandidate:
    free_mm: float
    installed_mm: float
    coil_bind_mm: float
    coil_reserve_mm: float
    compression_reserve_mm: float

    def __post_init__(self) -> None:
        if not all(isfinite(x) for x in (self.free_mm, self.installed_mm, self.coil_bind_mm,
                                         self.coil_reserve_mm, self.compression_reserve_mm)):
            raise ValueError("Значения кандидата должны быть конечными")
        if not 0 < self.coil_bind_mm < self.free_mm or self.installed_mm <= 0:
            raise ValueError("Длина смыкания должна быть положительной и меньше свободной; установленная длина положительна")
        if self.coil_reserve_mm < 0 or self.compression_reserve_mm < 0:
            raise ValueError("Требуемые запасы не могут быть отрицательными")


@dataclass(frozen=True)
class SpringCandidatePoint:
    travel_mm: float
    length_mm: float | None
    coil_clearance_mm: float | None
    compression_mm: float | None
    status: CandidateStatus


@dataclass(frozen=True)
class SpringComparison:
    candidate: SpringCandidate
    reference_installed_mm: float
    points: tuple[SpringCandidatePoint, ...]


def compare_spring_candidate(
    points: tuple[tuple[float, float | None], ...], reference_installed_mm: float, candidate: SpringCandidate,
) -> SpringComparison:
    """Новая длина в статике + изменение опор из исходной модели.

    Нулевая длина и ниже недопустима, равенство смыканию — конфликт,
    равенство свободной длине — без сжатия, а не разрешение хода. Равенство
    положительному запасу достаточно. Статусы определяются до округления;
    положения за упорами исходного расчёта сохраняются и не считаются достижимыми.
    """
    if not isfinite(reference_installed_mm) or reference_installed_mm <= 0:
        raise ValueError("Исходная установленная длина должна быть положительной и конечной")
    result: list[SpringCandidatePoint] = []
    for travel, original in points:
        if not isfinite(travel):
            raise ValueError("Ход должен быть конечным")
        if original is None:
            result.append(SpringCandidatePoint(travel, None, None, None, "missing"))
            continue
        if not isfinite(original) or original <= 0:
            raise ValueError("Исходная длина должна быть положительной и конечной")
        length = candidate.installed_mm + (original - reference_installed_mm)
        coil = length - candidate.coil_bind_mm
        compression = candidate.free_mm - length
        if not all(isfinite(x) for x in (length, coil, compression)):
            raise ValueError("Расчётная длина или запас не являются конечными")
        if length <= 0:
            status: CandidateStatus = "invalid"
        elif coil <= 0:
            status = "coil_bind"
        elif compression <= 0:
            status = "uncompressed"
        elif coil < candidate.coil_reserve_mm or compression < candidate.compression_reserve_mm:
            status = "reserve_short"
        else:
            status = "clear"
        result.append(SpringCandidatePoint(travel, length, coil, compression, status))
    return SpringComparison(candidate, reference_installed_mm, tuple(result))
