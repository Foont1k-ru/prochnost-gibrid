"""Каркас рассчитанной позы; не CAD, не физический контакт и не деформация."""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, pi, sin, sqrt
from typing import Literal

import numpy as np

from ..model.entities import Axle
from .double_wishbone import DoubleWishbone, Pose, RigidFiveLinkSolver
from .metrics import _wheel_directions
from .pose_view import Point, PoseView

SegmentKind = Literal["arm", "knuckle", "steering", "spring", "damper", "wheel"]
POINT_CODES = ("wheel_center", "uca_f_in", "uca_r_in", "ubj", "lca_f_in", "lca_r_in", "lbj",
               "tierod_in", "tierod_out", "spring_lo", "spring_up", "damper_lo", "damper_up")


@dataclass(frozen=True)
class Segment3D:
    start: Point
    end: Point
    kind: SegmentKind


@dataclass(frozen=True)
class Scene3D:
    travel_mm: float
    segments: tuple[Segment3D, ...]
    points: tuple[tuple[str, Point], ...] = ()

    def point(self, code: str) -> Point | None:
        return next((point for key, point in self.points if key == code), None)


def _point(values: np.ndarray) -> Point:
    return float(values[0]), float(values[1]), float(values[2])


def wheel_segments(model: RigidFiveLinkSolver, pose: Pose, axle: Axle, center: Point) -> list[Segment3D]:
    """Условный габарит колеса; ориентация совпадает с расчётом углов."""
    radius, width = axle.wheel.r_dynamic_mm, axle.wheel.width_mm
    if not all(isfinite(v) and 0 < v < 100000 for v in (radius, width)):
        raise ValueError("Радиус и ширина колеса должны быть положительными и конечными")
    normal, forward = _wheel_directions(model, pose, axle.setup.camber_deg, axle.setup.toe_deg_total / 2)
    up = np.cross(forward, normal) * model.sign
    position0 = np.array(center, dtype=float)
    rings: list[list[Point]] = []
    segments: list[Segment3D] = []
    n = 32
    for side in (-1, 1):
        ring = []
        for i in range(n):
            theta = 2 * pi * i / n
            position = position0 + side * width / 2 * normal + radius * (cos(theta) * forward + sin(theta) * up)
            ring.append(_point(position))
        rings.append(ring)
        segments.extend(Segment3D(ring[i], ring[(i + 1) % n], "wheel") for i in range(n))
    segments.extend(Segment3D(rings[0][i], rings[1][i], "wheel") for i in range(0, n, 4))
    return segments


def pose_scene(model: DoubleWishbone, pose: Pose, axle: Axle, frame: PoseView) -> Scene3D:
    """Линии опор и условный цилиндр колеса по той же ориентации, что в метриках.

    Кинематика не проверяет коллизии, контакт с дорогой, качение или материал.
    Цилиндр — габарит колеса, а не настоящая форма шины. Пружина — линия опор.
    """
    if frame.travel_mm != pose.travel_mm:
        raise ValueError("Кадр и положение относятся к разным ходам")
    steering_in = _point(model.points["tierod_in"])
    steering_out = _point(pose.point(model.points["tierod_out"], model.center0))
    segments = [
        Segment3D(frame.upper_front, frame.upper_ball, "arm"),
        Segment3D(frame.upper_rear, frame.upper_ball, "arm"),
        Segment3D(frame.upper_front, frame.upper_rear, "arm"),
        Segment3D(frame.lower_front, frame.lower_ball, "arm"),
        Segment3D(frame.lower_rear, frame.lower_ball, "arm"),
        Segment3D(frame.lower_front, frame.lower_rear, "arm"),
        Segment3D(frame.upper_ball, frame.lower_ball, "knuckle"),
        Segment3D(steering_in, steering_out, "steering"),
    ]
    if frame.spring is not None:
        segments.append(Segment3D(*frame.spring, "spring"))
    if frame.damper is not None:
        segments.append(Segment3D(*frame.damper, "damper"))
    segments.extend(wheel_segments(model, pose, axle, frame.center))
    points: list[tuple[str, Point]] = [
        ("wheel_center", frame.center), ("uca_f_in", frame.upper_front), ("uca_r_in", frame.upper_rear),
        ("ubj", frame.upper_ball), ("lca_f_in", frame.lower_front), ("lca_r_in", frame.lower_rear),
        ("lbj", frame.lower_ball), ("tierod_in", steering_in), ("tierod_out", steering_out),
    ]
    if frame.spring is not None:
        points.extend((("spring_lo", frame.spring[0]), ("spring_up", frame.spring[1])))
    if frame.damper is not None:
        points.extend((("damper_lo", frame.damper[0]), ("damper_up", frame.damper[1])))
    return Scene3D(frame.travel_mm, tuple(segments), tuple(points))


def scene_bounds(scenes: list[Scene3D]) -> tuple[Point, float] | None:
    """Сфера охватывает все кадры и не меняет масштаб при выборе хода/камеры."""
    points = [p for scene in scenes for segment in scene.segments for p in (segment.start, segment.end)]
    points.extend(point for scene in scenes for _, point in scene.points)
    if not points:
        return None
    if not all(isfinite(value) for point in points for value in point):
        raise ValueError("Координаты каркаса должны быть конечными")
    center = tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in range(3))
    c: Point = (center[0], center[1], center[2])
    radius = max(sqrt(sum((p[i] - c[i]) ** 2 for i in range(3))) for p in points)
    if not isfinite(radius):
        raise ValueError("Габариты каркаса должны быть конечными")
    return c, max(radius, 1.0)


def project_orthographic(point: Point, center: Point, yaw: float, elevation: float) -> tuple[float, float]:
    """Ортографическая камера, углы в радианах; вертикальная ось Z вверх."""
    if not all(isfinite(value) for value in (*point, *center, yaw, elevation)):
        raise ValueError("Параметры камеры и координаты должны быть конечными")
    x, y, z = (point[i] - center[i] for i in range(3))
    return (x * cos(yaw) + y * sin(yaw),
            -x * sin(yaw) * sin(elevation) + y * cos(yaw) * sin(elevation) + z * cos(elevation))
