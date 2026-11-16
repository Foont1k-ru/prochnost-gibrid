"""Пробное совмещение вручную заданных пар точек CAD и схемы в миллиметрах.

Жёсткое преобразование подбирается методом наименьших квадратов без масштаба и
отражения. Совпадение точек не подтверждает единицы, детали или безопасность.
"""
from __future__ import annotations

from dataclasses import dataclass

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
