"""Пробное совмещение вручную заданных пар точек CAD и схемы в миллиметрах.

Жёсткое преобразование подбирается методом наименьших квадратов без масштаба и
отражения. Совпадение точек не подтверждает единицы, детали или безопасность.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from .spatial_transform import RigidTransform

MAX_PAIRS = 20
MAX_COORDINATE_MM = 10_000_000.0
MIN_SPREAD_MM = 0.001
MIN_SPREAD_RATIO = 1e-6


@dataclass(frozen=True, slots=True)
class Registration:
    transform: RigidTransform
    residuals_mm: tuple[float, ...]
    rms_mm: float
    max_mm: float


def register_points(cad_points: object, project_points: object) -> Registration:
    """Найти CAD→проект, по 3–20 парам; обе системы в мм.

    Вырожденные или почти коллинеарные наборы отвергаются отдельно для каждой
    системы. Остатки всегда выдаются как измеренные величины, а не допуски.
    """
    try:
        cad = np.asarray(cad_points, dtype=np.float64)
        target = np.asarray(project_points, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("coordinates") from error
    if (cad.ndim != 2 or cad.shape[1:] != (3,) or target.shape != cad.shape or
            not 3 <= len(cad) <= MAX_PAIRS):
        raise ValueError("count")
    if (not np.isfinite(cad).all() or not np.isfinite(target).all() or
            np.any(np.abs(cad) > MAX_COORDINATE_MM) or np.any(np.abs(target) > MAX_COORDINATE_MM)):
        raise ValueError("coordinates")
    cad_center = cad.mean(axis=0)
    target_center = target.mean(axis=0)
    a, b = cad - cad_center, target - target_center
    for points in (a, b):
        values = np.linalg.svd(points, compute_uv=False)
        if values[0] < MIN_SPREAD_MM or values[1] < max(MIN_SPREAD_MM, values[0] * MIN_SPREAD_RATIO):
            raise ValueError("degenerate")
    u, cross_values, vt = np.linalg.svd(a.T @ b)
    if cross_values[0] <= 0 or cross_values[1] < cross_values[0] * MIN_SPREAD_RATIO:
        raise ValueError("degenerate")
    # Kabsch: only a right-handed rotation; never silently fit a reflection.
    correction = np.eye(3)
    correction[2, 2] = 1.0 if np.linalg.det(vt.T @ u.T) >= 0 else -1.0
    rotation = vt.T @ correction @ u.T
    translation = target_center - rotation @ cad_center
    transform = RigidTransform(tuple(tuple(float(x) for x in row) for row in rotation),  # type: ignore[arg-type]
                               tuple(float(x) for x in translation))  # type: ignore[arg-type]
    residuals = np.linalg.norm((a @ rotation.T) - b, axis=1)
    return Registration(transform, tuple(float(x) for x in residuals),
                        float(np.sqrt(np.mean(residuals ** 2))), float(np.max(residuals)))

@dataclass(frozen=True, slots=True)
class PointResidual:
    """Кандидатная точка и разность (преобразованная CAD − точка схемы), мм."""

    predicted_mm: tuple[float, float, float]
    delta_mm: tuple[float, float, float]
    distance_mm: float


@dataclass(frozen=True, slots=True)
class DistanceComparison:
    """Наибольшее расхождение длин среди отрезков между строками; индексы с нуля."""

    count: int
    rms_difference_mm: float
    first_row: int
    second_row: int
    cad_length_mm: float
    project_length_mm: float
    difference_mm: float  # project - CAD


@dataclass(frozen=True, slots=True)
class RegistrationEvaluation:
    fit: Registration
    points: tuple[PointResidual, ...]  # исходный порядок строк
    control_rms_mm: float | None
    control_max_mm: float | None
    fit_distances: DistanceComparison
    control_distances: DistanceComparison | None


def evaluate_registration(cad_points: object, project_points: object,
                          fit_mask: tuple[bool, ...]) -> RegistrationEvaluation:
    """Совместить по fit, затем отдельно оценить оставленные контрольные пары.

    Наличие контрольных пар не подтверждает независимость их источника; это
    определяет пользователь. Совпадающие точки между строками не допускаются.
    """
    try:
        cad = np.asarray(cad_points, dtype=np.float64)
        target = np.asarray(project_points, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("coordinates") from error
    if (cad.ndim != 2 or cad.shape[1:] != (3,) or target.shape != cad.shape or
            not 3 <= len(cad) <= MAX_PAIRS or len(fit_mask) != len(cad) or
            any(type(value) is not bool for value in fit_mask) or sum(fit_mask) < 3):
        raise ValueError("count")
    if (not np.isfinite(cad).all() or not np.isfinite(target).all() or
            np.any(np.abs(cad) > MAX_COORDINATE_MM) or np.any(np.abs(target) > MAX_COORDINATE_MM)):
        raise ValueError("coordinates")
    if len({tuple(row) for row in cad}) != len(cad) or len({tuple(row) for row in target}) != len(target):
        raise ValueError("duplicate")
    mask = np.asarray(fit_mask, dtype=bool)
    fit = register_points(cad[mask], target[mask])
    predicted = cad @ np.asarray(fit.transform.rotation).T + np.asarray(fit.transform.translation)
    delta = predicted - target
    distances = np.linalg.norm(delta, axis=1)
    points = tuple(PointResidual(tuple(map(float, pred)), tuple(map(float, diff)), float(distance))  # type: ignore[arg-type]
                   for pred, diff, distance in zip(predicted, delta, distances, strict=True))
    controls = distances[~mask]
    # Translation and rotation do not affect segment lengths. Compare fit-fit
    # separately from every segment involving at least one control row.
    groups: tuple[list[tuple[int, int, float, float]], list[tuple[int, int, float, float]]] = ([], [])
    for i, j in combinations(range(len(cad)), 2):
        cad_length = float(np.linalg.norm(cad[i] - cad[j]))
        project_length = float(np.linalg.norm(target[i] - target[j]))
        groups[0 if fit_mask[i] and fit_mask[j] else 1].append((i, j, cad_length, project_length))

    def summarize(segments: list[tuple[int, int, float, float]]) -> DistanceComparison:
        # max() retains the first segment in row order for exact ties.
        i, j, cad_length, project_length = max(segments, key=lambda v: abs(v[3] - v[2]))
        rms = float(np.sqrt(np.mean([(p - c) ** 2 for _, _, c, p in segments])))
        return DistanceComparison(len(segments), rms, i, j, cad_length, project_length,
                                  project_length - cad_length)

    return RegistrationEvaluation(fit, points,
                                  float(np.sqrt(np.mean(controls ** 2))) if len(controls) else None,
                                  float(np.max(controls)) if len(controls) else None,
                                  summarize(groups[0]), summarize(groups[1]) if groups[1] else None)
