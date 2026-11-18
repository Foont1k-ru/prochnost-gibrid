"""Простые формулы линейной пружины и шины в последовательном соединении."""
from __future__ import annotations

from math import isfinite, pi, sqrt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .double_wishbone import Array, DoubleWishbone, Pose


def spring_wheel_support(spring_force_n: float, motion_ratio: float) -> float:
    """Поддерживающая вертикальная сила у колеса из виртуальной работы.

    Знак MR = -dL/dh сохраняется: отрицательное значение означает, что
    сжимающая пружина действует в противоположном направлении.
    """
    if not isfinite(spring_force_n) or spring_force_n < 0 or not isfinite(motion_ratio):
        raise ValueError("Сила пружины должна быть неотрицательной, значения — конечными")
    result = spring_force_n * motion_ratio
    if not isfinite(result):
        raise ValueError("Сила на колесе не является конечной")
    return result


def wheel_rate(spring_rate_n_mm: float, motion_ratio: float) -> float:
    """Жёсткость на колесе, Н/мм; MR — ход пружины / ход колеса."""
    if not isfinite(spring_rate_n_mm) or spring_rate_n_mm < 0 or not isfinite(motion_ratio):
        raise ValueError("Жёсткость должна быть неотрицательной, значения должны быть конечными")
    return spring_rate_n_mm * motion_ratio**2


def ride_rate(wheel_rate_n_mm: float, tire_rate_n_mm: float) -> float:
    """Эквивалентная жёсткость пружины колеса и шины, Н/мм."""
    if not all(isfinite(v) for v in (wheel_rate_n_mm, tire_rate_n_mm)) or wheel_rate_n_mm < 0 or tire_rate_n_mm <= 0:
        raise ValueError("Жёсткость колеса должна быть неотрицательной, шины — положительной")
    return wheel_rate_n_mm * tire_rate_n_mm / (wheel_rate_n_mm + tire_rate_n_mm)


def ride_frequency_hz(ride_rate_n_mm: float, sprung_mass_kg: float) -> float:
    """Частота собственной системы в Гц: Н/мм переводятся в Н/м."""
    if not all(isfinite(v) for v in (ride_rate_n_mm, sprung_mass_kg)) or ride_rate_n_mm < 0 or sprung_mass_kg <= 0:
        raise ValueError("Жёсткость должна быть неотрицательной, масса — положительной")
    return sqrt(ride_rate_n_mm * 1000.0 / sprung_mass_kg) / (2.0 * pi)


def lower_arm_point(model: DoubleWishbone, pose: Pose, point: Array) -> Array:
    """Перемещает точку, жёстко закреплённую на нижнем рычаге."""
    import numpy as np
    from scipy.spatial.transform import Rotation

    from .double_wishbone import KinematicsError

    axis_origin = model.points["lca_f_in"]
    axis = model.points["lca_r_in"] - axis_origin
    axis = axis / np.linalg.norm(axis)
    original = model.points["lbj"] - axis_origin
    moved = pose.point(model.points["lbj"], model.center0) - axis_origin
    a = original - axis * np.dot(original, axis)
    b = moved - axis * np.dot(moved, axis)
    if np.linalg.norm(a) < 1e-9 or np.linalg.norm(b) < 1e-9:
        raise KinematicsError(pose.travel_mm, "шаровая расположена на оси нижнего рычага")
    angle = np.arctan2(np.dot(axis, np.cross(a, b)), np.dot(a, b))
    return axis_origin + Rotation.from_rotvec(axis * angle).apply(point - axis_origin)


def lower_arm_spring_length(model: DoubleWishbone, pose: Pose, lower: Array, upper: Array) -> float:
    """Расстояние от точки на нижнем рычаге до неподвижной верхней точки."""
    import numpy as np

    return float(np.linalg.norm(upper - lower_arm_point(model, pose, lower)))


def lower_arm_motion_ratio(model: DoubleWishbone, travel_mm: float, lower: Array, upper: Array, step_mm: float = 0.01) -> float:
    """Локальное отношение сжатия пружины к ходу колеса центральной разностью."""
    if not isfinite(step_mm) or step_mm <= 0:
        raise ValueError("Шаг должен быть положительным и конечным")
    low, high = model.sweep([travel_mm - step_mm, travel_mm + step_mm])
    a = lower_arm_spring_length(model, low, lower, upper)
    b = lower_arm_spring_length(model, high, lower, upper)
    return (a - b) / (2 * step_mm)


def sprung_mass_per_corner(total_mass_kg: float, axle_fraction: float, unsprung_mass_per_corner_kg: float) -> float:
    """Подрессоренная масса одного угла оси при симметричной развесовке."""
    if not all(isfinite(v) for v in (total_mass_kg, axle_fraction, unsprung_mass_per_corner_kg)):
        raise ValueError("Масса и доля оси должны быть конечными")
    if total_mass_kg <= 0 or not 0 < axle_fraction < 1 or unsprung_mass_per_corner_kg < 0:
        raise ValueError("Неверная масса, доля оси или неподрессоренная масса")
    mass = total_mass_kg * axle_fraction / 2 - unsprung_mass_per_corner_kg
    if mass <= 0:
        raise ValueError("Подрессоренная масса угла должна быть положительной")
    return mass


def axle_roll_stiffness_nm_per_degree(wheel_rate_n_mm: float, track_mm: float, arb_nm_per_degree: float = 0.0) -> float:
    """Жёсткость двух одинаковых колёс и отдельно заданного стабилизатора."""
    if not all(isfinite(v) for v in (wheel_rate_n_mm, track_mm, arb_nm_per_degree)):
        raise ValueError("Жёсткости и колея должны быть конечными")
    if wheel_rate_n_mm < 0 or track_mm <= 0 or arb_nm_per_degree < 0:
        raise ValueError("Жёсткости не могут быть отрицательными, колея должна быть положительной")
    return 2 * wheel_rate_n_mm * (track_mm / 2) ** 2 / 1000 * pi / 180 + arb_nm_per_degree


def progressive_spring_rate(points: list[tuple[float, float]], compression_mm: float) -> float:
    """Локальная жёсткость таблицы «сжатие, сила» без экстраполяции.

    В изломах и за концами таблицы производная не определена. Полный график
    должен состоять из не менее чем двух конечных точек с возрастающими
    сжатием и силой.
    """
    if len(points) < 2 or not isfinite(compression_mm):
        raise ValueError("Нужны минимум две точки и конечное сжатие")
    if any(not isfinite(x) or not isfinite(force) for x, force in points):
        raise ValueError("Точки характеристики должны быть конечными")
    if any(bx <= ax or bf <= af for (ax, af), (bx, bf) in zip(points, points[1:], strict=False)):
        raise ValueError("Сжатие и сила в характеристике должны строго возрастать")
    for (x0, f0), (x1, f1) in zip(points, points[1:], strict=False):
        if x0 < compression_mm < x1:
            return (f1 - f0) / (x1 - x0)
    raise ValueError("Локальная жёсткость в изломе или вне диапазона не определена")


def lower_arm_motion_ratio_at_pose(model: DoubleWishbone, pose: Pose, lower: Array, upper: Array) -> float:
    """Отношение сжатия пружины к ходу из мгновенной скорости рычага."""
    import numpy as np
    from scipy.spatial.transform import Rotation

    from .double_wishbone import KinematicsError
    from .screw_axis import instantaneous_motion

    origin = model.points["lca_f_in"]
    axis = model.points["lca_r_in"] - origin
    axis = axis / np.linalg.norm(axis)
    initial_ball = model.points["lbj"] - origin
    current_ball = pose.point(model.points["lbj"], model.center0) - origin
    initial_radial = initial_ball - axis * np.dot(initial_ball, axis)
    current_radial = current_ball - axis * np.dot(current_ball, axis)
    radial_sq = float(np.dot(current_radial, current_radial))
    if radial_sq < 1e-18 or np.linalg.norm(initial_radial) < 1e-9:
        raise KinematicsError(pose.travel_mm, "шаровая расположена на оси нижнего рычага")
    angle = np.arctan2(np.dot(axis, np.cross(initial_radial, current_radial)), np.dot(initial_radial, current_radial))
    current_lower = origin + Rotation.from_rotvec(axis * angle).apply(lower - origin)
    spring_vector = upper - current_lower
    spring_length = float(np.linalg.norm(spring_vector))
    if spring_length < 1e-9:
        raise KinematicsError(pose.travel_mm, "опоры пружины совпадают")
    motion = instantaneous_motion(model, pose)
    ball_velocity = motion.linear + np.cross(motion.angular, current_ball + origin - pose.center)
    arm_speed = float(np.dot(axis, np.cross(current_radial, ball_velocity)) / radial_sq)
    lower_velocity = arm_speed * np.cross(axis, current_lower - origin)
    return float(np.dot(spring_vector, lower_velocity) / spring_length)
