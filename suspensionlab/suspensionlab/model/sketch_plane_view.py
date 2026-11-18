"""Ортографический выбор координатных плоскостей в схематичном 3D-виде.

Квадранты имеют условный размер и не являются гранями детали. Координаты
клика — в системе проекции; при перекрытии выбирается ближайшая плоскость.
"""
from __future__ import annotations

from math import cos, radians, sin
from typing import Literal

Plane = Literal["XY", "XZ", "YZ"]
Vector = tuple[float, float, float]
PLANES: tuple[Plane, ...] = ("XY", "XZ", "YZ")
PLANE_AXES: dict[Plane, tuple[int, int, int]] = {"XY": (0, 1, 2), "XZ": (0, 2, 1), "YZ": (1, 2, 0)}
NEAR = 0.18
FAR = 1.18


def camera_basis(yaw: float, pitch: float) -> tuple[Vector, Vector, Vector]:
    yaw, pitch = radians(yaw), radians(pitch)
    sy, cy, sp, cp = sin(yaw), cos(yaw), sin(pitch), cos(pitch)
    return (-sy, cy, 0.), (-sp * cy, -sp * sy, cp), (cp * cy, cp * sy, sp)


def dot(a: Vector, b: Vector) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def plane_point(plane: Plane, u: float, v: float) -> Vector:
    first, second, _ = PLANE_AXES[plane]
    xyz = [0., 0., 0.]
    xyz[first], xyz[second] = u, v
    return xyz[0], xyz[1], xyz[2]


def project(point: Vector, yaw: float, pitch: float) -> tuple[float, float, float]:
    right, up, front = camera_basis(yaw, pitch)
    return dot(point, right), dot(point, up), dot(point, front)


def pick_plane(x: float, y: float, yaw: float, pitch: float) -> Plane | None:
    right, up, front = camera_basis(yaw, pitch)
    base = tuple(x * right[i] + y * up[i] for i in range(3))
    hits: list[tuple[float, Plane]] = []
    for plane in PLANES:
        first, second, normal = PLANE_AXES[plane]
        if abs(front[normal]) < 1e-9:
            continue  # Edge-on planes cannot be picked as surfaces.
        depth = -base[normal] / front[normal]
        u, v = base[first] + depth * front[first], base[second] + depth * front[second]
        if NEAR <= u <= FAR and NEAR <= v <= FAR:
            hits.append((depth, plane))
    return max(hits)[1] if hits else None
