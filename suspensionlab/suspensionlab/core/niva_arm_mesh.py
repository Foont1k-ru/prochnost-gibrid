"""Только иллюстративная сетка: не B-rep, не импорт STEP и не CAD-деталь."""
from __future__ import annotations

import math

import numpy as np

from ..model.niva_arm_views import ArmView
from .cad_mesh import CadMesh


def _basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    direction = axis / np.linalg.norm(axis)
    ref = np.array([0., 0., 1.]) if abs(direction[2]) < .9 else np.array([0., 1., 0.])
    u = np.cross(direction, ref)
    u /= np.linalg.norm(u)
    return direction, u, np.cross(direction, u)


def _surface(center: np.ndarray, axis: np.ndarray, profile: list[tuple[float, float]],
             *, sides: int = 16) -> list[np.ndarray]:
    """Поверхность вращения профиля (высота, радиус), без булевых операций."""
    direction, u, v = _basis(axis)
    rings = []
    for height, radius in profile:
        rings.append([center + direction * height + radius * (u * math.cos(2*math.pi*i/sides) +
                                                              v * math.sin(2*math.pi*i/sides))
                      for i in range(sides)])
    result: list[np.ndarray] = []
    for first, second in zip(rings, rings[1:], strict=False):
        for i in range(sides):
            j = (i + 1) % sides
            result.extend((np.array((first[i], first[j], second[j])),
                           np.array((first[i], second[j], second[i]))))
    return result


def schematic_mesh(view: ArmView) -> CadMesh:
    """Рисует прямые условные стержни и символические шарниры, без размеров изделий.

    Шаровой узел: кольцевой корпус с выемкой, головка и условный палец вдоль Z.
    Втулочный: кольцевая втулка и палец вдоль Y. Оси и размеры условные.
    """
    triangles: list[np.ndarray] = []
    for a, b in view.segments:
        p, q = np.asarray(a), np.asarray(b)
        axis = q - p
        length = float(np.linalg.norm(axis))
        triangles.extend(_surface(p, axis, [(0, 0), (0, 8), (length, 8), (length, 0)]))
    for point, kind in zip(view.points, view.joint_kinds, strict=True):
        p = np.asarray(point)
        if kind == 'ball':
            # A hollow annular housing around a ball-shaped head. These are
            # separate illustration surfaces, not a validated contact assembly.
            axis = np.array([0., 0., 1.])
            triangles.extend(_surface(p, axis, [(-6, 8.3), (-6, 15), (6, 15), (6, 8.3),
                                                (3, 9.84), (0, 10.3), (-3, 9.84), (-6, 8.3)]))
            profile = [(10*math.cos(math.pi*i/12), 10*math.sin(math.pi*i/12)) for i in range(13)]
            triangles.extend(_surface(p, axis, profile))
            triangles.extend(_surface(p, axis, [(8, 0), (8, 4), (25, 4), (25, 0)]))
        else:
            axis = np.array([0., 1., 0.])
            triangles.extend(_surface(p, axis, [(-9, 5), (-9, 13), (9, 13), (9, 5), (-9, 5)]))
            triangles.extend(_surface(p, axis, [(-14, 0), (-14, 4), (14, 4), (14, 0)]))
    array = np.asarray(triangles, dtype=np.float64)
    return CadMesh(array, face_count=len(array))
