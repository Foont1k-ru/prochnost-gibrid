"""Приближённые точки и расстояния по отображаемой треугольной сетке.

Это не геометрия STEP B-rep, не CAD-измерение и не данные расчётного проекта.
"""
from __future__ import annotations

from math import dist

import numpy as np


def point_on_projected_triangle(triangle: np.ndarray, projected: np.ndarray,
                                x: float, y: float) -> tuple[float, float, float] | None:
    """Интерполировать точку исходного 3D-треугольника по экранной проекции.

    Отказываемся от почти вырожденной проекции и точек вне треугольника:
    пиксельная растеризация иногда закрашивает соседний пиксель за гранью.
    """
    triangle = np.asarray(triangle, dtype=float)
    projected = np.asarray(projected, dtype=float)
    if (triangle.shape != (3, 3) or projected.shape != (3, 2) or not np.all(np.isfinite(triangle)) or
            not np.all(np.isfinite(projected)) or not np.isfinite(x) or not np.isfinite(y)):
        return None
    a, b, c = projected
    ab, ac = b - a, c - a
    point = np.array([x, y]) - a
    determinant = ab[0] * ac[1] - ab[1] * ac[0]
    scale = max(float(ab @ ab), float(ac @ ac), float((c - b) @ (c - b)))
    if scale < 1e-12 or abs(determinant) <= scale * 1e-8:
        return None
    u = (point[0] * ac[1] - point[1] * ac[0]) / determinant
    v = (ab[0] * point[1] - ab[1] * point[0]) / determinant
    weights = np.array([1 - u - v, u, v])
    if np.any(weights < -1e-9) or np.any(weights > 1 + 1e-9):
        return None
    result = weights @ triangle
    if not np.all(np.isfinite(result)):
        return None
    return float(result[0]), float(result[1]), float(result[2])


def measurement_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Расстояние между двумя приближёнными точками; в единицах сетки CAD."""
    if not all(np.isfinite(v) for v in (*a, *b)):
        raise ValueError("Координаты должны быть конечными")
    return dist(a, b)
