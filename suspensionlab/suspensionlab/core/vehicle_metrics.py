"""Проверяемые оценки оси крена и переноса нагрузки по заданным исходным данным.

Это формулы первого приближения: они не моделируют крен кузова,
податливость, распределение сил в звеньях или динамику шины.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, isfinite, radians


@dataclass(frozen=True)
class RollCenter3D:
    """Центр крена в общей системе автомобиля ISO, мм."""

    x_mm: float
    y_mm: float
    z_mm: float

    def __post_init__(self) -> None:
        if not all(isfinite(v) for v in (self.x_mm, self.y_mm, self.z_mm)):
            raise ValueError("Координаты центра крена должны быть конечными")


@dataclass(frozen=True)
class RollAxis:
    """Геометрическая ось через два заданных центра крена."""

    front: RollCenter3D
    rear: RollCenter3D
    pitch_deg: float
    lateral_angle_deg: float

    def height_at_x(self, x_mm: float) -> float:
        """Высота оси при указанном X, включая линейную экстраполяцию."""
        if not isfinite(x_mm):
            raise ValueError("Координата должна быть конечной")
        fraction = (self.front.x_mm - x_mm) / (self.front.x_mm - self.rear.x_mm)
        return self.front.z_mm + fraction * (self.rear.z_mm - self.front.z_mm)


def roll_axis(front: RollCenter3D, rear: RollCenter3D) -> RollAxis:
    """Положительный наклон означает, что задний центр выше переднего."""
    wheelbase = front.x_mm - rear.x_mm
    if wheelbase <= 1e-9:
        raise ValueError("Передний центр крена должен быть впереди заднего")
    return RollAxis(
        front=front,
        rear=rear,
        pitch_deg=degrees(atan2(rear.z_mm - front.z_mm, wheelbase)),
        lateral_angle_deg=degrees(atan2(rear.y_mm - front.y_mm, wheelbase)),
    )


def geometric_load_transfer_n(axle_mass_kg: float, lateral_acceleration_m_s2: float, roll_center_height_mm: float, track_mm: float) -> float:
    """Геометрическая составляющая по модели `m*a_y*h_RC/track`, Н.

    Значение задаётся в конвенции ТЗ как перенос на одну сторону; это не
    суммарная разница реакций левого и правого колеса. Знак ускорения и
    высоты сохраняется. Масса задаётся вызывающей стороной явно.
    """
    if not all(isfinite(v) for v in (axle_mass_kg, lateral_acceleration_m_s2, roll_center_height_mm, track_mm)):
        raise ValueError("Параметры переноса нагрузки должны быть конечными")
    if axle_mass_kg <= 0 or track_mm <= 0:
        raise ValueError("Масса оси и колея должны быть положительными")
    return axle_mass_kg * lateral_acceleration_m_s2 * roll_center_height_mm / track_mm


def static_roll_angle_deg(
    sprung_mass_kg: float,
    lateral_acceleration_m_s2: float,
    roll_arm_mm: float,
    front_stiffness_nm_per_deg: float,
    rear_stiffness_nm_per_deg: float,
    *,
    gravity_m_s2: float = 9.80665,
) -> float:
    """Квазистатическая линейная оценка крена по заданному плечу и жёсткостям.

    Формула из ТЗ: `φ = m*a_y*h/(K_front+K_rear−m*g*h)` в радианах.
    При неположительном знаменателе равновесие модели неустойчиво или не
    определено, поэтому возвращается исключение, а не фиктивный угол.
    """
    values = (sprung_mass_kg, lateral_acceleration_m_s2, roll_arm_mm,
              front_stiffness_nm_per_deg, rear_stiffness_nm_per_deg, gravity_m_s2)
    if not all(isfinite(v) for v in values):
        raise ValueError("Параметры оценки крена должны быть конечными")
    if sprung_mass_kg <= 0 or gravity_m_s2 <= 0 or roll_arm_mm < 0:
        raise ValueError("Масса и ускорение свободного падения положительны, плечо неотрицательно")
    if front_stiffness_nm_per_deg < 0 or rear_stiffness_nm_per_deg < 0:
        raise ValueError("Жёсткости осей не могут быть отрицательными")
    arm_m = roll_arm_mm / 1000.0
    # Н·м/градус → Н·м/радиан.
    stiffness_nm_per_rad = (front_stiffness_nm_per_deg + rear_stiffness_nm_per_deg) / radians(1)
    denominator = stiffness_nm_per_rad - sprung_mass_kg * gravity_m_s2 * arm_m
    if denominator <= 0:
        raise ValueError("Линейное равновесие крена неустойчиво или не определено")
    return degrees(sprung_mass_kg * lateral_acceleration_m_s2 * arm_m / denominator)
