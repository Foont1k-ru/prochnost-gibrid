"""Временное упрощение сетки только для движения камеры в CAD-просмотре.

Это не исправление STEP и не геометрия проекта. При остановке показывается
исходная полная сетка. Группы обрабатываются отдельно, чтобы не сливать детали.
"""
from __future__ import annotations

import numpy as np

from .cad_mesh import CadMesh

INTERACTION_THRESHOLD = 12_000


def interaction_triangles(mesh: CadMesh) -> np.ndarray:
    """Сжать мелкие треугольники в пространственную сетку для быстрого кадра.

    Мелкие группы сохраняются целиком. Шаг ограничен размером каждой группы;
    при полном вырождении группы оставляем её исходные треугольники.
    Это эвристика, а не гарантированное ограничение количества треугольников.
    """
    triangles = mesh.triangles
    if len(triangles) <= INTERACTION_THRESHOLD:
        return triangles
    diagonal = float(np.linalg.norm(np.ptp(triangles.reshape(-1, 3), axis=0)))
    if diagonal == 0:
        return triangles
    parts = mesh.triangle_parts
    if parts is None:
        groups = [triangles]
    else:
        order = np.argsort(parts, kind="stable")
        splits = np.flatnonzero(np.diff(parts[order])) + 1
        groups = [triangles[indices] for indices in np.split(order, splits)]
    chunks = []
    for group in groups:
        if len(group) < 250:
            chunks.append(group)
            continue
        origin = group.min(axis=(0, 1))
        extent = float(np.ptp(group.reshape(-1, 3), axis=0).max())
        step = min(diagonal / 50, extent / 16)
        if step <= 0:
            chunks.append(group)
            continue
        cells = np.rint((group - origin) / step).astype(np.int64)
        keep = np.any(np.cross(cells[:, 1] - cells[:, 0], cells[:, 2] - cells[:, 0]) != 0, axis=1)
        cells = cells[keep]
        if not len(cells):
            chunks.append(group)
            continue
        # Ключи сортируются по вершинам; ориентация совпадающих треугольников не важна.
        # Координаты ограничены шагом extent/16 и фактическим размером модели.
        # np.unique(axis=0) избегает переполнения при упаковке координат в одно число.
        vertices = np.sort(cells.view([("x", np.int64), ("y", np.int64), ("z", np.int64)]).reshape(-1, 3), axis=1)
        _, index = np.unique(vertices, axis=0, return_index=True)
        chunks.append(origin + cells[np.sort(index)].astype(np.float64) * step)
    return np.concatenate(chunks, axis=0)
