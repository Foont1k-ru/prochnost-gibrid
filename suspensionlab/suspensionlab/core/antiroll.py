"""Идеализированный стабилизатор со стойками при раздельном ходе колёс.

Нижние концы стоек на нижних рычагах; верхние — на жёстких плечах вокруг
общей оси Y. Длина стоек постоянна, стержень работает только на кручение.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import acos, atan2, ceil, degrees, hypot, isfinite, pi, radians
from typing import Literal

import numpy as np
from scipy.spatial.transform import Rotation

from ..model.entities import Axle
from .double_wishbone import Array, DoubleWishbone, KinematicsError, Pose
from .springs import lower_arm_motion_ratio_at_pose, lower_arm_point
from .sweep import travel_grid


@dataclass(frozen=True)
class AntiRollScenario:
    """Ось через (x, 0, z) параллельна Y; крутильная жёсткость, Н·м/рад."""

    axis_x_mm: float
    axis_z_mm: float
    torsion_rate_nm_rad: float
    max_angle_step_deg: float = 15.0

    def __post_init__(self) -> None:
        if not all(isfinite(v) for v in (self.axis_x_mm, self.axis_z_mm, self.torsion_rate_nm_rad, self.max_angle_step_deg)):
            raise ValueError("Параметры стабилизатора должны быть конечными")
        if self.torsion_rate_nm_rad < 0 or not 0 < self.max_angle_step_deg < 90:
            raise ValueError("Жёсткость неотрицательна, шаг угла должен быть между 0 и 90 градусами")


@dataclass(frozen=True)
class LinkState:
    """Геометрия стойки и сжимающее усилие (отрицательное — растяжение)."""

    lower_mm: tuple[float, float, float]
    upper_mm: tuple[float, float, float]
    length_mm: float
    tilt_from_vertical_deg: float
    arm_angle_deg: float
    arm_rate_rad_per_mm: float
    compression_force_n: float
    wheel_resistance_n: float


@dataclass(frozen=True)
class AntiRollState:
    """Две стойки и упругое скручивание заданной модели."""

    left_travel_mm: float
    right_travel_mm: float
    left: LinkState
    right: LinkState
    twist_deg: float
    torque_nm: float
    strain_energy_j: float


@dataclass(frozen=True)
class AntiRollPoint:
    """Запрошенная пара ходов и результат либо причина отказа."""

    left_travel_mm: float
    right_travel_mm: float
    state: AntiRollState | None
    error: str | None
    # Те же позы, которые использовались при расчёте стойки; на отказе обе отсутствуют.
    left_pose: Pose | None = None
    right_pose: Pose | None = None


@dataclass(frozen=True)
class AntiRollSweep:
    """Результаты в порядке запроса; после отказа ветвь не продолжается."""

    points: tuple[AntiRollPoint, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _ArmSide:
    model: DoubleWishbone
    lower: Array
    upper: Array
    initial_length: float


class AntiRollStudy:
    """Идеализированный двухсторонний расчёт; параметры проекта не угадываются."""

    def __init__(self, axle: Axle, scenario: AntiRollScenario) -> None:
        self.scenario = scenario
        self.origin = np.array((scenario.axis_x_mm, 0.0, scenario.axis_z_mm))
        self.axis = np.array((0.0, 1.0, 0.0))
        try:
            p, q = axle.hardpoints["arb_lo"], axle.hardpoints["arb_up"]
        except KeyError as exc:
            raise ValueError("Не заданы обе опоры стойки стабилизатора") from exc
        if not all(isfinite(v) for v in (*p.as_tuple(), *q.as_tuple())):
            raise ValueError("Опоры стоек стабилизатора должны быть конечными")
        sides = []
        for side, sign in (("left", 1), ("right", -1)):
            model = DoubleWishbone(axle, side)
            lower = np.array((p.x, sign * p.y, p.z))
            upper = np.array((q.x, sign * q.y, q.z))
            length = float(np.linalg.norm(upper - lower))
            radius = float(np.linalg.norm(np.cross(upper - self.origin, self.axis)))
            if not isfinite(length) or not isfinite(radius):
                raise ValueError("Длина стойки и плеча должна быть конечной")
            if length <= 1e-9 or radius <= 1e-9:
                raise ValueError("Стойка нулевой длины или крепление лежит на оси стабилизатора")
            sides.append(_ArmSide(model, lower, upper, length))
        self.left, self.right = sides
        self.limitations = (
            "rigid_arms_and_drop_links", "shaft_axis_parallel_y", "linear_torsion_no_preload",
            "independent_angles_on_shared_axis", "project_arb_rate_not_used",
            "bushings_bending_and_joint_limits_not_modeled", "collisions_and_strength_not_checked",
            "fixed_body_and_ground", "sampled_path_not_continuously_verified",
        )
        # Статика должна иметь единственную локальную ветвь.
        self._link(self.left, self.left.model.initial_pose(), 0.0)
        self._link(self.right, self.right.model.initial_pose(), 0.0)

    def _link(self, side: _ArmSide, pose: Pose, previous: float) -> tuple[float, Array, Array, float, float]:
        lower = lower_arm_point(side.model, pose, side.lower)
        r = side.upper - self.origin
        axial = self.axis * float(np.dot(r, self.axis))
        radial = r - axial
        cross = np.cross(self.axis, radial)
        delta = self.origin + axial - lower
        a, b = float(np.dot(delta, radial)), float(np.dot(delta, cross))
        c = (side.initial_length**2 - float(np.dot(delta, delta)) - float(np.dot(radial, radial))) / 2
        magnitude = hypot(a, b)
        if not all(isfinite(v) for v in (a, b, c, magnitude)):
            raise KinematicsError(pose.travel_mm, "неконечная геометрия стабилизатора")
        if magnitude < 1e-9 or abs(c) > magnitude * (1 + 1e-12):
            raise KinematicsError(pose.travel_mm, "стойка стабилизатора не достигает плеча")
        phase = atan2(b, a)
        alpha = acos(max(-1.0, min(1.0, c / magnitude)))
        candidates = [phase + alpha, phase - alpha]
        candidates = [x + round((previous - x) / (2 * pi)) * 2 * pi for x in candidates]
        angle = min(candidates, key=lambda x: abs(x - previous))
        if abs(angle - previous) > radians(self.scenario.max_angle_step_deg):
            raise KinematicsError(pose.travel_mm, "слишком большой скачок угла плеча стабилизатора")
        upper = self.origin + Rotation.from_rotvec(self.axis * angle).apply(r)
        vector = upper - lower
        length = float(np.linalg.norm(vector))
        if length < 1e-9 or abs(length - side.initial_length) > 1e-5:
            raise KinematicsError(pose.travel_mm, "невязка или нулевая длина стойки стабилизатора")
        unit = vector / length
        moment_arm = float(np.dot(unit, np.cross(self.axis, upper - self.origin)))
        if abs(moment_arm) < 1e-7:
            raise KinematicsError(pose.travel_mm, "стойка в сингулярном положении относительно плеча")
        numerator = lower_arm_motion_ratio_at_pose(side.model, pose, side.lower, upper)
        angular_rate = numerator / moment_arm
        if not isfinite(angular_rate):
            raise KinematicsError(pose.travel_mm, "неопределённая скорость плеча стабилизатора")
        return angle, lower, upper, moment_arm, angular_rate

    def _state(self, left_pose: Pose, right_pose: Pose, left_angle: float, right_angle: float) -> tuple[AntiRollState, float, float]:
        la, ll, lu, lm, lr = self._link(self.left, left_pose, left_angle)
        ra, rl, ru, rm, rr = self._link(self.right, right_pose, right_angle)
        twist = la - ra
        torque = self.scenario.torsion_rate_nm_rad * twist
        def make_link(lower: Array, upper: Array, angle: float, rate: float, moment_arm: float, sign: int) -> LinkState:
            vector = upper - lower
            length = float(np.linalg.norm(vector))
            tilt = degrees(acos(max(-1.0, min(1.0, float(vector[2]) / length))))
            compression = sign * torque * 1000 / moment_arm
            resistance = sign * torque * 1000 * rate
            if not all(isfinite(v) for v in (tilt, compression, resistance)):
                raise ValueError("Результат по стойке стабилизатора не является конечным")
            return LinkState((float(lower[0]), float(lower[1]), float(lower[2])),
                             (float(upper[0]), float(upper[1]), float(upper[2])), length, tilt, degrees(angle),
                             rate, compression, resistance)
        energy = 0.5 * self.scenario.torsion_rate_nm_rad * twist**2
        if not isfinite(torque) or not isfinite(energy):
            raise ValueError("Момент или энергия стабилизатора не являются конечными")
        state = AntiRollState(left_pose.travel_mm, right_pose.travel_mm, make_link(ll, lu, la, lr, lm, 1),
                              make_link(rl, ru, ra, rr, rm, -1), degrees(twist), torque, energy)
        return state, la, ra

    def sweep_travel(
        self,
        from_mm: float,
        to_mm: float,
        *,
        mode: Literal["bounce", "opposed"] = "opposed",
        step_mm: float = 1.0,
    ) -> AntiRollSweep:
        """Выдаёт сетку ходов обеих сторон: одинаковых либо противоположных.

        Это ходы колёс относительно неподвижного кузова, не моделирование
        реального угла крена. Для произвольной траектории вызовите sweep.
        """
        if mode not in ("bounce", "opposed"):
            raise ValueError("Режим должен быть bounce или opposed")
        grid = travel_grid(from_mm, to_mm, max_spacing_mm=step_mm)
        sign = 1 if mode == "bounce" else -1
        return self.sweep([(h, sign * h) for h in grid], max_step_mm=step_mm)

    def sweep(self, travels_mm: list[tuple[float, float]], *, max_step_mm: float = 1.0) -> AntiRollSweep:
        """По заданным парам ходов продолжает обе стороны с началом от статики."""
        if not isfinite(max_step_mm) or max_step_mm <= 0:
            raise ValueError("Шаг хода должен быть положительным и конечным")
        if len(travels_mm) > 5000 or not all(isfinite(v) for pair in travels_mm for v in pair):
            raise ValueError("Ходы должны быть конечными; разрешено не более 5000 точек")
        if any(len(pair) != 2 for pair in travels_mm):
            raise ValueError("Каждая точка должна содержать ходы двух колёс")
        previous_left = previous_right = 0.0
        total_steps = 0
        for left, right in travels_mm:
            step_count = max(abs(left - previous_left), abs(right - previous_right)) / max_step_mm
            if not isfinite(step_count) or step_count > 20000:
                raise ValueError("Слишком много шагов продолжения стабилизатора")
            total_steps += max(1, ceil(step_count))
            if total_steps > 20000:
                raise ValueError("Слишком много шагов продолжения стабилизатора")
            previous_left, previous_right = left, right
        lp, rp = self.left.model.initial_pose(), self.right.model.initial_pose()
        la = ra = 0.0
        results: list[AntiRollPoint] = []
        failure = None
        for left, right in travels_mm:
            if failure is None:
                start_left, start_right = lp.travel_mm, rp.travel_mm
                count = max(1, ceil(max(abs(left - start_left), abs(right - start_right)) / max_step_mm))
                try:
                    for i in range(1, count + 1):
                        left_h = start_left + (left - start_left) * i / count
                        right_h = start_right + (right - start_right) * i / count
                        lp, rp = self.left.model._step(lp, left_h), self.right.model._step(rp, right_h)
                        state, la, ra = self._state(lp, rp, la, ra)
                except (KinematicsError, ValueError) as exc:
                    failure = str(exc)
            results.append(AntiRollPoint(left, right, state if failure is None else None, failure,
                                         lp if failure is None else None, rp if failure is None else None))
        return AntiRollSweep(tuple(results), self.limitations)
