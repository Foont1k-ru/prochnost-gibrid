"""Математика будущего OpenGL-просмотра; сам рендерер здесь не включается.

Матрица рассчитана на столбец ``(x, y, z, 1)`` после центрирования и
нормализации вершин по радиусу. Это не преобразование CAD-геометрии.
"""
from __future__ import annotations

from math import cos, sin

import numpy as np


def clip_matrix(yaw: float, elevation: float, zoom: float, width: int, height: int,
                margin: float = 24., offset: tuple[float, float] = (0., 0.)) -> np.ndarray:
    """Ортографическая камера с тем же масштабом и панорамированием, что CPU-вид.

    Размер и отступы задаются в физических пикселях, как в screen_projection.
    Матрица намеренно не задаёт глубину: порядок и выбор видимых поверхностей
    должны определяться отдельно, согласованно с фактической отрисовкой.
    """
    values = (yaw, elevation, zoom, margin, *offset)
    if (not all(np.isfinite(v) for v in values) or zoom <= 0 or margin < 0 or
            width <= 0 or height <= 0):
        raise ValueError("Некорректные параметры камеры")
    sy, cy = sin(yaw), cos(yaw)
    se, ce = sin(elevation), cos(elevation)
    scale = max(1., min(width - margin, height - margin)) * zoom / 2
    matrix = np.zeros((4, 4), dtype=np.float64)
    matrix[0, :3] = (cy * 2 * scale / width, sy * 2 * scale / width, 0)
    matrix[1, :3] = (-sy * se * 2 * scale / height, cy * se * 2 * scale / height,
                     ce * 2 * scale / height)
    matrix[0, 3] = 2 * offset[0] / width
    matrix[1, 3] = -2 * offset[1] / height
    matrix[3, 3] = 1
    return matrix


def normalized_vertices(triangles: np.ndarray, center: np.ndarray, radius: float) -> np.ndarray:
    """Центрировать в float64 до перехода к float32 для передачи в GPU.

    Временные массивы ограничены блоком; сама копия float32 всё же занимает
    36 байт на треугольник и должна учитываться наряду с CPU- и GPU-буферами.
    """
    if (triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or center.shape != (3,) or
            not np.isfinite(radius) or radius <= 0 or not np.isfinite(center).all()):
        raise ValueError("Некорректные границы сетки")
    vertices = np.empty(triangles.shape, dtype=np.float32)
    for start in range(0, len(triangles), 4096):
        chunk = triangles[start:start + 4096]
        if not np.isfinite(chunk).all():
            raise ValueError("Некорректные координаты сетки")
        normalized = (chunk.astype(np.float64, copy=False) - center) / radius
        if not np.isfinite(normalized).all() or np.any(np.abs(normalized) > np.finfo(np.float32).max):
            raise ValueError("Координаты не помещаются в буфер")
        vertices[start:start + len(chunk)] = normalized
    return vertices
