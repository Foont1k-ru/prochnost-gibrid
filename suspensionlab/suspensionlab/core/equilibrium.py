"""Условное равновесие одной пружины при заданной вертикальной нагрузке.

Одномерная модель не рассчитывает контакт шины, прочие силы и устойчивость.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np

from ..model.entities import Axle
from .double_wishbone import DoubleWishbone
from .spring_characteristics import SpringCharacteristic, SpringState, spring_state
from .springs import lower_arm_motion_ratio_at_pose, lower_arm_spring_length, spring_wheel_support


class EquilibriumError(ValueError):
    """Равновесие невозможно оценить в вычисленной точке."""

    def __init__(self, travel_mm: float, reason: str) -> None:
        self.travel_mm = travel_mm
        self.reason = reason
        super().__init__(f"Равновесие при ходе {travel_mm:+.3f} мм: {reason}")


@dataclass(frozen=True)
class EquilibriumSample:
    """Эквивалентная поддерживающая сила и её разность с заданной нагрузкой."""

    travel_mm: float
    spring: SpringState
    motion_ratio: float
    wheel_support_n: float
    residual_n: float


@dataclass(frozen=True)
class EquilibriumResult:
    """Проверенный интервал и отдельно рассчитанная оценка его середины."""

    lower: EquilibriumSample
    upper: EquilibriumSample
    estimate: EquilibriumSample
    evaluations: int
    limitations: tuple[str, ...]


class SpringEquilibrium:
    """Пружина с нижней опорой на рычаге, заданная длина при ходе 0.

    Расстояние опор определяет только изменение длины пружины. Для правой
    стороны исходные точки модели зеркалируются автоматически.
    """

    def __init__(
        self,
        axle: Axle,
        static_spring_length_mm: float,
        *,
        side: Literal["left", "right"] = "left",
        coil_bind_length_mm: float | None = None,
        max_step_mm: float = 2.0,
    ) -> None:
        if not isfinite(static_spring_length_mm) or static_spring_length_mm <= 0:
            raise ValueError("Статическая длина пружины должна быть положительной и конечной")
        if not isfinite(max_step_mm) or max_step_mm <= 0:
            raise ValueError("Шаг продолжения должен быть положительным и конечным")
        self.model = DoubleWishbone(axle, side)
        self.characteristic = SpringCharacteristic(
            axle.spring.free_len_mm, axle.spring.rate_N_mm, tuple(axle.spring.progressive), coil_bind_length_mm,
        )
        try:
            p, q = axle.hardpoints["spring_lo"], axle.hardpoints["spring_up"]
        except KeyError as exc:
            raise ValueError("Не заданы опоры пружины") from exc
        self.lower = np.array([p.x, p.y * self.model.sign, p.z], dtype=float)
        self.upper = np.array([q.x, q.y * self.model.sign, q.z], dtype=float)
        if not np.all(np.isfinite(self.lower)) or not np.all(np.isfinite(self.upper)):
            raise ValueError("Координаты опор пружины должны быть конечными")
        self.initial_mount_length = lower_arm_spring_length(self.model, self.model.initial_pose(), self.lower, self.upper)
        if self.initial_mount_length <= 1e-9:
            raise ValueError("Опоры пружины совпадают")
        self.static_spring_length_mm = static_spring_length_mm
        self.max_step_mm = max_step_mm
        self.limitations = (
            "spring_length_change_equals_mount_distance_change",
            "spring_preload_not_applied",
            "only_spring_and_vertical_wheel_load",
            "tire_contact_and_other_forces_not_modeled",
            "equilibrium_stability_not_checked",
            "continuous_reachable_branch_not_guaranteed",
        ) + (("spring_coil_bind_unspecified",) if coil_bind_length_mm is None else ())

    def evaluate(self, travel_mm: float, load_n: float) -> EquilibriumSample:
        """Рассчитывает локальное условие баланса для заданной силы в Н."""
        if not isfinite(load_n) or load_n <= 0:
            raise ValueError("Нагрузка на колесо должна быть положительной и конечной")
        pose = self.model.solve(travel_mm, max_step_mm=self.max_step_mm)
        distance = lower_arm_spring_length(self.model, pose, self.lower, self.upper)
        length = self.static_spring_length_mm + (distance - self.initial_mount_length)
        if not isfinite(length) or length <= 0:
            raise EquilibriumError(travel_mm, "неположительная или неконечная длина пружины")
        state = spring_state(self.characteristic, length)
        if state.force_n is None:
            raise EquilibriumError(travel_mm, f"неопределённая сила пружины: {state.status}")
        ratio = lower_arm_motion_ratio_at_pose(self.model, pose, self.lower, self.upper)
        support = spring_wheel_support(state.force_n, ratio)
        residual = support - load_n
        if not isfinite(residual):
            raise EquilibriumError(travel_mm, "невязка силы не является конечной")
        return EquilibriumSample(travel_mm, state, ratio, support, residual)

    def find(
        self,
        load_n: float,
        from_travel_mm: float,
        to_travel_mm: float,
        *,
        travel_tolerance_mm: float = 0.01,
    ) -> EquilibriumResult:
        """Уточняет один интервал смены знака методом бисекции.

        Не находит все решения и не гарантирует непрерывность непроверенных
        частей интервала. Численные или физические ошибки в оценённых точках
        прерывают поиск. Допуск относится к ширине интервала, не силе.
        """
        if not all(isfinite(v) for v in (load_n, from_travel_mm, to_travel_mm, travel_tolerance_mm)):
            raise ValueError("Нагрузка, границы и допуск должны быть конечными")
        if load_n <= 0 or from_travel_mm >= to_travel_mm or travel_tolerance_mm <= 0:
            raise ValueError("Нагрузка и допуск должны быть положительными, границы — возрастать")
        lower = self.evaluate(from_travel_mm, load_n)
        upper = self.evaluate(to_travel_mm, load_n)
        count = 2
        if lower.residual_n == 0:
            return EquilibriumResult(lower, lower, lower, count, self.limitations)
        if upper.residual_n == 0:
            return EquilibriumResult(upper, upper, upper, count, self.limitations)
        if (lower.residual_n > 0) == (upper.residual_n > 0):
            raise ValueError("На концах интервала силы должны быть по разные стороны от нагрузки")
        for _ in range(80):
            if upper.travel_mm - lower.travel_mm <= travel_tolerance_mm:
                break
            middle_travel = lower.travel_mm + (upper.travel_mm - lower.travel_mm) / 2
            if middle_travel in (lower.travel_mm, upper.travel_mm):
                break
            middle = self.evaluate(middle_travel, load_n)
            count += 1
            if middle.residual_n == 0:
                return EquilibriumResult(middle, middle, middle, count, self.limitations)
            if (middle.residual_n > 0) == (lower.residual_n > 0):
                lower = middle
            else:
                upper = middle
        if upper.travel_mm - lower.travel_mm > travel_tolerance_mm:
            raise ValueError("Не удалось уточнить ход до заданного допуска")
        estimate_travel = lower.travel_mm + (upper.travel_mm - lower.travel_mm) / 2
        estimate = self.evaluate(estimate_travel, load_n)
        return EquilibriumResult(lower, upper, estimate, count + 1, self.limitations)
