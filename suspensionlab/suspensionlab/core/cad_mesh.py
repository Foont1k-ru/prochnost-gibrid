"""Ограниченная треугольная сетка для экспериментального просмотра CAD."""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin

import numpy as np

MAX_TRIANGLES = 100_000
MAX_COORDINATE = 10_000_000.0  # мм; защитный предел просмотра, не проверка модели


@dataclass(frozen=True)
class CadMesh:
    """Треугольники в мм, ориентировочная визуализация, не расчётная геометрия."""

    triangles: np.ndarray
    face_count: int

    def __post_init__(self) -> None:
        try:
            mesh = np.array(self.triangles, dtype=np.float64, copy=True)
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError("Некорректная треугольная сетка") from error
        if (mesh.ndim != 3 or mesh.shape[1:] != (3, 3) or not 0 < len(mesh) <= MAX_TRIANGLES or
                not np.all(np.isfinite(mesh)) or np.any(np.abs(mesh) > MAX_COORDINATE) or
                not 0 < self.face_count <= MAX_TRIANGLES):
            raise ValueError("Сетка пуста, слишком велика или содержит некорректные координаты")
        mesh.flags.writeable = False
        object.__setattr__(self, "triangles", mesh)

    def bounds(self) -> tuple[np.ndarray, float]:
        vertices = self.triangles.reshape(-1, 3)
        center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
        radius = float(np.linalg.norm(vertices - center, axis=1).max())
        return center, max(radius, 1.)


def project_triangles(mesh: CadMesh, yaw: float, elevation: float) -> tuple[np.ndarray, np.ndarray]:
    """Ортографическая проекция и порядок рисования; не точный алгоритм скрытия граней."""
    if not np.isfinite(yaw) or not np.isfinite(elevation):
        raise ValueError("Углы камеры должны быть конечными")
    center, _ = mesh.bounds()
    points = mesh.triangles - center
    sy, cy = sin(yaw), cos(yaw)
    se, ce = sin(elevation), cos(elevation)
    right = np.array([cy, sy, 0.])
    up = np.array([-sy * se, cy * se, ce])
    depth = np.cross(right, up)
    projected = np.stack((points @ right, points @ up), axis=-1)
    distance = (points @ depth).mean(axis=1)
    return projected, np.argsort(distance, kind="stable")
