"""Ограниченная треугольная сетка для экспериментального просмотра CAD."""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin

import numpy as np

from .cad_parts import MAX_PART_GROUPS, MAX_PART_NAME

MAX_TRIANGLES = 100_000
MAX_COORDINATE = 10_000_000.0  # мм; защитный предел просмотра, не проверка модели


@dataclass(frozen=True)
class CadMesh:
    """Треугольники в мм, ориентировочная визуализация, не расчётная геометрия."""

    triangles: np.ndarray
    face_count: int
    skipped_faces: int = 0
    recovered_faces: int = 0
    part_names: tuple[str, ...] = ()
    triangle_parts: np.ndarray | None = None

    def __post_init__(self) -> None:
        try:
            mesh = np.array(self.triangles, dtype=np.float64, copy=True)
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError("Некорректная треугольная сетка") from error
        if (mesh.ndim != 3 or mesh.shape[1:] != (3, 3) or not 0 < len(mesh) <= MAX_TRIANGLES or
                not np.all(np.isfinite(mesh)) or np.any(np.abs(mesh) > MAX_COORDINATE) or
                not 0 < self.face_count <= MAX_TRIANGLES or
                not 0 <= self.skipped_faces < self.face_count or
                not 0 <= self.recovered_faces <= self.face_count - self.skipped_faces):
            raise ValueError("Сетка пуста, слишком велика или содержит некорректные координаты")
        mesh.flags.writeable = False
        object.__setattr__(self, "triangles", mesh)
        if self.triangle_parts is None:
            if self.part_names:
                raise ValueError("Нет сопоставления деталей")
        else:
            parts = np.asarray(self.triangle_parts)
            if (parts.shape != (len(mesh),) or parts.dtype.kind not in "iu" or
                    not 0 < len(self.part_names) <= MAX_PART_GROUPS or
                    any(not isinstance(name, str) or not name or len(name) > MAX_PART_NAME or
                        not all(c.isprintable() for c in name) for name in self.part_names) or
                    np.any(parts < 0) or np.any(parts >= len(self.part_names))):
                raise ValueError("Некорректные группы деталей")
            parts = np.array(parts, dtype=np.int32, copy=True)
            parts.flags.writeable = False
            object.__setattr__(self, "triangle_parts", parts)
            object.__setattr__(self, "part_names", tuple(self.part_names))

    def isolated(self, group: int) -> CadMesh:
        """Только отображение группы; счётчики относятся ко всей исходной модели."""
        if self.triangle_parts is None or not 0 <= group < len(self.part_names):
            raise ValueError("Группа не найдена")
        selected = self.triangles[self.triangle_parts == group]
        if not len(selected):
            raise ValueError("В группе нет треугольников")
        return CadMesh(selected, self.face_count, self.skipped_faces, self.recovered_faces)

    def bounds(self) -> tuple[np.ndarray, float]:
        vertices = self.triangles.reshape(-1, 3)
        center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
        radius = float(np.linalg.norm(vertices - center, axis=1).max())
        return center, max(radius, 1.)


def project_points(triangles: np.ndarray, center: np.ndarray, yaw: float, elevation: float) -> tuple[np.ndarray, np.ndarray]:
    """Проекция заранее центрированной камеры без повторного вычисления границ."""
    if not np.isfinite(yaw) or not np.isfinite(elevation):
        raise ValueError("Углы камеры должны быть конечными")
    points = triangles - center
    sy, cy = sin(yaw), cos(yaw)
    se, ce = sin(elevation), cos(elevation)
    x, y, z = points[:, :, 0], points[:, :, 1], points[:, :, 2]
    projected = np.stack((cy * x + sy * y, -sy * se * x + cy * se * y + ce * z), axis=-1)
    distance = (sy * ce * x - cy * ce * y + se * z).mean(axis=1)
    return projected, np.argsort(distance, kind="stable")


def project_triangles(mesh: CadMesh, yaw: float, elevation: float) -> tuple[np.ndarray, np.ndarray]:
    """Ортографическая проекция и порядок рисования; не точный алгоритм скрытия граней."""
    center, _ = mesh.bounds()
    return project_points(mesh.triangles, center, yaw, elevation)
