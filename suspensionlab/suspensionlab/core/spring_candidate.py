"""Предварительное сравнение длин другой пружины по сохранённой сетке хода."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from .spring_characteristics import SpringCharacteristic, spring_state

CandidateStatus = Literal["missing", "invalid", "coil_bind", "uncompressed", "reserve_short", "clear"]
ForceStatus = Literal["disabled", "missing", "invalid", "coil_bind", "calculated", "overflow"]


@dataclass(frozen=True)
class SpringCandidate:
    free_mm: float
    installed_mm: float
    coil_bind_mm: float
    coil_reserve_mm: float
    compression_reserve_mm: float
    linear_rate_n_mm: float | None = None

    def __post_init__(self) -> None:
        if not all(isfinite(x) for x in (self.free_mm, self.installed_mm, self.coil_bind_mm,
                                         self.coil_reserve_mm, self.compression_reserve_mm)):
            raise ValueError("Значения кандидата должны быть конечными")
        if not 0 < self.coil_bind_mm < self.free_mm or self.installed_mm <= 0:
            raise ValueError("Длина смыкания должна быть положительной и меньше свободной; установленная длина положительна")
        if self.coil_reserve_mm < 0 or self.compression_reserve_mm < 0:
            raise ValueError("Требуемые запасы не могут быть отрицательными")
        if self.linear_rate_n_mm is not None and (not isfinite(self.linear_rate_n_mm) or self.linear_rate_n_mm <= 0):
            raise ValueError("Линейная жёсткость должна быть положительной и конечной")


@dataclass(frozen=True)
class CandidateGeometry:
    """Подписанные разности и численные условия в одной исходной точке."""

    length_mm: float
    coil_clearance_mm: float
    compression_mm: float
    coil_reserve_ok: bool
    compression_reserve_ok: bool
    status: CandidateStatus


def candidate_geometry(candidate: SpringCandidate, length_mm: float) -> CandidateGeometry:
    """Категории без округления; границы контакта важны и при нулевом запасе.

    Это только сравнение заданных чисел, не проверка удержания, монтажа,
    прочности, соседних положений или безопасности.
    """
    coil = length_mm - candidate.coil_bind_mm
    compression = candidate.free_mm - length_mm
    if not all(isfinite(x) for x in (length_mm, coil, compression)):
        raise ValueError("Расчётная длина или запас не являются конечными")
    coil_ok = length_mm > 0 and coil > 0 and coil >= candidate.coil_reserve_mm
    compression_ok = length_mm > 0 and compression > 0 and compression >= candidate.compression_reserve_mm
    if length_mm <= 0:
        status: CandidateStatus = "invalid"
    elif coil <= 0:
        status = "coil_bind"
    elif compression <= 0:
        status = "uncompressed"
    elif not coil_ok or not compression_ok:
        status = "reserve_short"
    else:
        status = "clear"
    return CandidateGeometry(length_mm, coil, compression, coil_ok, compression_ok, status)


@dataclass(frozen=True)
class SpringCandidatePoint:
    travel_mm: float
    length_mm: float | None
    coil_clearance_mm: float | None
    compression_mm: float | None
    status: CandidateStatus
    force_n: float | None
    force_status: ForceStatus


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
    Необязательная линейная сила — сила пружины, не реакция колеса и не
    равновесие; смыкание, неположительную длину и пропуски не подменяем нулём.
    """
    if not isfinite(reference_installed_mm) or reference_installed_mm <= 0:
        raise ValueError("Исходная установленная длина должна быть положительной и конечной")
    characteristic = (SpringCharacteristic(candidate.free_mm, candidate.linear_rate_n_mm,
                                            coil_bind_length_mm=candidate.coil_bind_mm)
                      if candidate.linear_rate_n_mm is not None else None)
    result: list[SpringCandidatePoint] = []
    for travel, original in points:
        if not isfinite(travel):
            raise ValueError("Ход должен быть конечным")
        if original is None:
            force_status: ForceStatus = "disabled" if characteristic is None else "missing"
            result.append(SpringCandidatePoint(travel, None, None, None, "missing", None, force_status))
            continue
        if not isfinite(original) or original <= 0:
            raise ValueError("Исходная длина должна быть положительной и конечной")
        length = candidate.installed_mm + (original - reference_installed_mm)
        geometry = candidate_geometry(candidate, length)
        coil, compression, status = geometry.coil_clearance_mm, geometry.compression_mm, geometry.status
        force = None
        if characteristic is None:
            force_status = "disabled"
        elif status == "invalid":
            force_status = "invalid"
        elif status == "coil_bind":
            force_status = "coil_bind"
        else:
            force = spring_state(characteristic, length).force_n
            if force is None or not isfinite(force):
                force, force_status = None, "overflow"
            else:
                force_status = "calculated"
        result.append(SpringCandidatePoint(travel, length, coil, compression, status, force, force_status))
    return SpringComparison(candidate, reference_installed_mm, tuple(result))


@dataclass(frozen=True)
class ForceExtremum:
    """Индекс исходной строки и значение силы без экранного округления."""

    row: int
    travel_mm: float
    force_n: float


@dataclass(frozen=True)
class CandidateForceSummary:
    total: int
    calculated: int
    disabled: int
    missing: int
    invalid: int
    coil_bind: int
    overflow: int
    minimum: ForceExtremum | None
    maximum: ForceExtremum | None


def summarize_candidate_force(comparison: SpringComparison) -> CandidateForceSummary:
    """Крайние силы только на доступных строках; при равенстве — первая.

    Пропуски и смыкания не превращаются в нули. Даже при отсутствии пропусков
    крайние точки не гарантируют экстремумы между ними или физическую достижимость.
    """
    counts = dict.fromkeys(("calculated", "disabled", "missing", "invalid", "coil_bind", "overflow"), 0)
    values: list[ForceExtremum] = []
    for row, point in enumerate(comparison.points):
        counts[point.force_status] += 1
        if point.force_status == "calculated" and point.force_n is not None:
            values.append(ForceExtremum(row, point.travel_mm, point.force_n))
    return CandidateForceSummary(
        total=len(comparison.points), calculated=counts["calculated"], disabled=counts["disabled"],
        missing=counts["missing"], invalid=counts["invalid"], coil_bind=counts["coil_bind"],
        overflow=counts["overflow"], minimum=min(values, key=lambda p: p.force_n, default=None),
        maximum=max(values, key=lambda p: p.force_n, default=None),
    )


@dataclass(frozen=True)
class CandidateGeometryExtremum:
    """Минимальная подписанная разность в сохранённой строке, без округления."""

    row: int
    travel_mm: float
    value_mm: float
    condition_ok: bool


@dataclass(frozen=True)
class CandidateGeometrySummary:
    total: int
    coil_short: int
    compression_short: int
    minimum_coil: CandidateGeometryExtremum | None
    minimum_compression: CandidateGeometryExtremum | None


def summarize_candidate_geometry(
    candidate: SpringCandidate, points: tuple[tuple[float, float], ...],
) -> CandidateGeometrySummary:
    """Минимумы и количества только по переданным точкам; при равенстве первая строка.

    Точка отказа без данных и промежутки не восстанавливаются. Минимум и
    выполнение численного условия не подтверждают физическую пригодность.
    """
    coil_values: list[CandidateGeometryExtremum] = []
    compression_values: list[CandidateGeometryExtremum] = []
    for row, (travel, length) in enumerate(points):
        if not isfinite(travel):
            raise ValueError("Ход должен быть конечным")
        geometry = candidate_geometry(candidate, length)
        coil_values.append(CandidateGeometryExtremum(row, travel, geometry.coil_clearance_mm,
                                                     geometry.coil_reserve_ok))
        compression_values.append(CandidateGeometryExtremum(row, travel, geometry.compression_mm,
                                                            geometry.compression_reserve_ok))
    return CandidateGeometrySummary(
        len(points), sum(not p.condition_ok for p in coil_values),
        sum(not p.condition_ok for p in compression_values),
        min(coil_values, key=lambda p: p.value_mm, default=None),
        min(compression_values, key=lambda p: p.value_mm, default=None),
    )
