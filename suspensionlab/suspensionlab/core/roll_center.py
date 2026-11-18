"""Проекционный мгновенный и симметричный геометрический центры крена."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .double_wishbone import DoubleWishbone, KinematicsError, Pose
from .screw_axis import instantaneous_motion


@dataclass(frozen=True)
class ProjectedInstantCenter:
    """Однородные координаты (Y, Z, W); при W=0 центр находится на бесконечности."""

    y: float
    z: float
    w: float

    @property
    def at_infinity(self) -> bool:
        """Конечное пересечение отсутствует при параллельных нормалях."""
        return abs(self.w) < 1e-10


def projected_instant_center(model: DoubleWishbone, pose: Pose) -> ProjectedInstantCenter:
    """Пересечение нормалей к проекциям скоростей верхней и нижней шаровой.

    Для общего пространственного движения это проекционная конструкция,
    а не полная силовая модель центра крена.
    """
    motion = instantaneous_motion(model, pose)
    lines = []
    for code in ("ubj", "lbj"):
        point = pose.point(model.points[code], model.center0)
        velocity = motion.linear + np.cross(motion.angular, point - pose.center)
        vy, vz = velocity[1], velocity[2]
        speed = float(np.hypot(vy, vz))
        if speed < 1e-12:
            raise KinematicsError(pose.travel_mm, "направление скорости шаровой в проекции не определено")
        lines.append(np.array([vy / speed, vz / speed, -(vy * point[1] + vz * point[2]) / speed]))
    center = np.cross(lines[0], lines[1])
    norm = float(np.hypot(center[0], center[1]))
    if abs(center[2]) < 1e-10:
        if norm < 1e-10:
            raise KinematicsError(pose.travel_mm, "нормали мгновенного центра совпадают")
        center = center / norm
        return ProjectedInstantCenter(float(center[0]), float(center[1]), 0.0)
    center = center / center[2]
    return ProjectedInstantCenter(float(center[0]), float(center[1]), 1.0)


def symmetric_roll_center_height(model: DoubleWishbone, pose: Pose) -> float:
    """Высота геометрического ЦК на Y=0 при зеркальной оси и равном ходе.

    Пятно контакта приближено вертикальной проекцией центра на Z=0.
    Для асимметричного хода и крена кузова эта функция неприменима.
    """
    ic = projected_instant_center(model, pose)
    contact = np.array([float(pose.center[1]), 0.0, 1.0])
    force_line = np.cross(contact, np.array([ic.y, ic.z, ic.w]))
    # aY + bZ + c = 0; при Y=0 получаем Z=-c/b.
    if abs(force_line[1]) < 1e-10:
        raise KinematicsError(pose.travel_mm, "центр крена в проекции не определён или бесконечен")
    return float(-force_line[2] / force_line[1])


def roll_center_from_projected_motion(
    left: DoubleWishbone, left_pose: Pose, right: DoubleWishbone, right_pose: Pose
) -> tuple[float, float]:
    """Пересечение проекционных линий пятно контакта — МЦ обеих сторон.

    Координаты возвращаются в системе неподвижного кузова. При совпадающих
    или параллельных линиях пересечение не определяется. Идеализированная
    геометрия пятна контакта и ограничения проекционного метода те же, что
    у `symmetric_roll_center_height`; положение земли и крен кузова здесь
    не пересчитываются.
    """
    if left.side != "left" or right.side != "right":
        raise ValueError("Ожидаются левая, затем правая сторона оси")
    lines = []
    for model, pose in ((left, left_pose), (right, right_pose)):
        ic = projected_instant_center(model, pose)
        line = np.cross(np.array([pose.center[1], 0.0, 1.0]), np.array([ic.y, ic.z, ic.w]))
        length = float(np.hypot(line[0], line[1]))
        if length < 1e-12:
            raise KinematicsError(pose.travel_mm, "линия пятно контакта — мгновенный центр не определена")
        lines.append(line / length)
    point = np.cross(lines[0], lines[1])
    if abs(point[2]) < 1e-10:
        raise KinematicsError(0.0, "линии обеих сторон параллельны или совпадают; центр крена не определён")
    return (float(point[0] / point[2]), float(point[1] / point[2]))
