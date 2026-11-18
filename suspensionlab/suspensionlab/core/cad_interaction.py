"""Временное упрощение сетки только для движения камеры в CAD-просмотре.

Это не исправление STEP и не геометрия проекта. При остановке показывается
исходная полная сетка. Группы обрабатываются отдельно, чтобы не сливать детали.
"""
from __future__ import annotations

import numpy as np

from .cad_mesh import CadMesh

INTERACTION_THRESHOLD = 12_000
LARGE_MESH_THRESHOLD = 200_000
LARGE_MESH_TARGET = 60_000


def interaction_triangles(mesh: CadMesh) -> np.ndarray:
    return interaction_geometry(mesh)[0]


def interaction_geometry(mesh: CadMesh, highlight: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray | None]:
    """Сжать мелкие треугольники в пространственную сетку для быстрого кадра.

    Мелкие группы сохраняются целиком. Шаг ограничен размером каждой группы;
    при полном вырождении группы оставляем её исходные треугольники.
    Это эвристика, а не гарантированное ограничение количества треугольников.
    """
    triangles = mesh.triangles
    if highlight is not None and (highlight.shape != (len(triangles),) or highlight.dtype.kind != "b"):
        raise ValueError("Некорректная маска подсветки")
    if len(triangles) <= INTERACTION_THRESHOLD:
        return triangles, highlight
    diagonal = float(np.linalg.norm(np.ptp(triangles.reshape(-1, 3), axis=0)))
    if diagonal == 0:
        return triangles, highlight
    # Выделенные и обычные грани разных деталей нельзя сливать вместе.
    parts = mesh.triangle_parts
    keys = np.zeros(len(triangles), dtype=np.int32) if parts is None else parts.copy()
    if highlight is not None:
        keys = keys * 2 + highlight.astype(np.int32)
    order = np.argsort(keys, kind="stable")
    splits = np.flatnonzero(np.diff(keys[order])) + 1
    groups = np.split(order, splits)
    chunks = []
    masks = []
    for indices in groups:
        # На крупных сборках избегаем полной сортировки вершин миллионов
        # треугольников. Это только временная выборка для движения камеры.
        if len(triangles) > LARGE_MESH_THRESHOLD:
            quota = max(250, int(len(indices) * LARGE_MESH_TARGET / len(triangles)))
            if len(indices) > quota:
                indices = indices[np.linspace(0, len(indices) - 1, quota, dtype=np.int64)]
        group = triangles[indices]
        selected = bool(highlight[indices[0]]) if highlight is not None else False
        if len(group) < 250:
            chunks.append(group)
            masks.append(np.full(len(group), selected, dtype=bool))
            continue
        origin = group.min(axis=(0, 1))
        extent = float(np.ptp(group.reshape(-1, 3), axis=0).max())
        step = min(diagonal / 50, extent / 16)
        if step <= 0:
            chunks.append(group)
            masks.append(np.full(len(group), selected, dtype=bool))
            continue
        cells = np.rint((group - origin) / step).astype(np.int64)
        keep = np.any(np.cross(cells[:, 1] - cells[:, 0], cells[:, 2] - cells[:, 0]) != 0, axis=1)
        cells = cells[keep]
        if not len(cells):
            chunks.append(group)
            masks.append(np.full(len(group), selected, dtype=bool))
            continue
        # Ключи сортируются по вершинам; ориентация совпадающих треугольников не важна.
        # Координаты ограничены шагом extent/16 и фактическим размером модели.
        # np.unique(axis=0) избегает переполнения при упаковке координат в одно число.
        vertices = np.sort(cells.view([("x", np.int64), ("y", np.int64), ("z", np.int64)]).reshape(-1, 3), axis=1)
        _, index = np.unique(vertices, axis=0, return_index=True)
        chunk = origin + cells[np.sort(index)].astype(np.float64) * step
        chunks.append(chunk)
        masks.append(np.full(len(chunk), selected, dtype=bool))
    return np.concatenate(chunks, axis=0), np.concatenate(masks) if highlight is not None else None
