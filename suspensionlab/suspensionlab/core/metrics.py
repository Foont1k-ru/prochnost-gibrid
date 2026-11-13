"""Ограниченный набор проверяемых геометрических метрик двухрычажной оси."""
from __future__ import annotations

from dataclasses import dataclass
from math import asin, atan2, cos, degrees, isfinite, radians, sin, tan

import numpy as np

from .double_wishbone import DoubleWishbone, KinematicsError, Pose


@dataclass(frozen=True)
class CornerMetrics:
    """Углы в градусах, расстояния в миллиметрах; относительно кузова."""

    camber_deg: float
    toe_deg: float
    caster_deg: float
    kpi_deg: float
    included_angle_deg: float
    scrub_radius_mm: float
    mechanical_trail_mm: float
    lateral_displacement_mm: float
    longitudinal_displacement_mm: float


def _wheel_directions(
    model: DoubleWishbone, pose: Pose, static_camber_deg: float, static_toe_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    """Нормаль и продольная ось колеса с начальной настройкой."""
    if not all(isfinite(v) and abs(v) < 89.0 for v in (static_camber_deg, static_toe_deg)):
        raise ValueError("Статические углы должны быть конечными и меньше 89° по модулю")
    side = model.sign
    camber = radians(static_camber_deg)
    toe = radians(static_toe_deg)
    initial_normal = np.array([sin(toe), side * cos(toe), -tan(camber) * cos(toe)])
    initial_normal /= np.linalg.norm(initial_normal)
    initial_forward = np.array([cos(toe), -side * sin(toe), 0.0])
    return pose.rotation @ initial_normal, pose.rotation @ initial_forward

def corner_metrics(
    model: DoubleWishbone,
    pose: Pose,
    *,
    static_camber_deg: float = 0.0,
    static_toe_deg: float = 0.0,
) -> CornerMetrics:
    """Метрики относительно исходной ориентации колеса и неподвижного кузова.

    Начальные развал и схождение задаются явно на одно колесо; по умолчанию
    они нулевые. Они влияют только на ориентацию плоскости колеса, но не
    изменяют координаты шарниров или ось поворота. Пятно контакта приближённо
    находится вертикально под центром колеса.
    """
    side = model.sign
    normal, forward = _wheel_directions(model, pose, static_camber_deg, static_toe_deg)
    ubj = pose.point(model.points["ubj"], model.center0)
    lbj = pose.point(model.points["lbj"], model.center0)
    axis = ubj - lbj
    if abs(axis[2]) < 1e-9:
        raise KinematicsError(pose.travel_mm, "ось поворота не пересекает плоскость земли")
    ground_intersection = lbj - axis * (lbj[2] / axis[2])
    return CornerMetrics(
        camber_deg=-degrees(atan2(normal[2], side * normal[1])),
        toe_deg=-side * degrees(atan2(forward[1], forward[0])),
        caster_deg=degrees(atan2(-axis[0], axis[2])),
        kpi_deg=degrees(atan2(-side * axis[1], axis[2])),
        included_angle_deg=degrees(asin(float(np.clip(abs(np.dot(normal, axis / np.linalg.norm(axis))), 0, 1)))),
        scrub_radius_mm=float(side * (pose.center[1] - ground_intersection[1])),
        mechanical_trail_mm=float(ground_intersection[0] - pose.center[0]),
        lateral_displacement_mm=float(side * (pose.center[1] - model.center0[1])),
        longitudinal_displacement_mm=float(pose.center[0] - model.center0[0]),
    )


@dataclass(frozen=True)
class CornerDerivatives:
    """Мгновенные производные относительно вертикального хода колеса."""

    camber_deg_per_25mm: float
    toe_deg_per_25mm: float
    lateral_mm_per_mm: float
    longitudinal_mm_per_mm: float


def corner_derivatives(
    model: DoubleWishbone,
    pose: Pose,
    *,
    static_camber_deg: float = 0.0,
    static_toe_deg: float = 0.0,
) -> CornerDerivatives:
    """Точные локальные производные углов проекций через винтовую скорость."""
    from .screw_axis import instantaneous_motion

    normal, forward = _wheel_directions(model, pose, static_camber_deg, static_toe_deg)
    motion = instantaneous_motion(model, pose)
    normal_rate = np.cross(motion.angular, normal)
    forward_rate = np.cross(motion.angular, forward)
    camber_denominator = normal[1] ** 2 + normal[2] ** 2
    toe_denominator = forward[0] ** 2 + forward[1] ** 2
    if camber_denominator < 1e-16 or toe_denominator < 1e-16:
        raise KinematicsError(pose.travel_mm, "проекция оси колеса вырождена")
    camber = -model.sign * (normal[1] * normal_rate[2] - normal[2] * normal_rate[1]) / camber_denominator
    toe = -model.sign * (forward[0] * forward_rate[1] - forward[1] * forward_rate[0]) / toe_denominator
    return CornerDerivatives(
        camber_deg_per_25mm=degrees(camber) * 25,
        toe_deg_per_25mm=degrees(toe) * 25,
        lateral_mm_per_mm=float(model.sign * motion.linear[1]),
        longitudinal_mm_per_mm=float(motion.linear[0]),
    )
