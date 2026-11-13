"""Мгновенная винтовая ось кулака из дифференциала жёстких связей."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .double_wishbone import Array, DoubleWishbone, KinematicsError, Pose


@dataclass(frozen=True)
class ScrewMotion:
    """Скорости на 1 мм хода и ось; для чистого переноса ось отсутствует."""

    linear: Array
    angular: Array
    axis_point: Array | None
    axis_direction: Array | None
    pitch_mm: float | None


def instantaneous_motion(model: DoubleWishbone, pose: Pose) -> ScrewMotion:
    """Дифференцирует связи по вертикальному ходу и вычисляет винтовую ось."""
    _, jac = model._system(pose.center, pose.rotation, pose.travel_mm)
    model._condition(jac, pose.travel_mm)
    rhs = np.array([0., 0., 0., 0., 0., 1.])
    try:
        velocity = np.linalg.solve(jac, rhs)
    except np.linalg.LinAlgError as exc:
        raise KinematicsError(pose.travel_mm, "невозможно определить мгновенное движение") from exc
    linear, angular = velocity[:3], velocity[3:]
    omega2 = float(angular @ angular)
    if omega2 < 1e-24:
        return ScrewMotion(linear, angular, None, None, None)
    point = pose.center + np.cross(angular, linear) / omega2
    return ScrewMotion(linear, angular, point, angular / np.sqrt(omega2), float(angular @ linear / omega2))
