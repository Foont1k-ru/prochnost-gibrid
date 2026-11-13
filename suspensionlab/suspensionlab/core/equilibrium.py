"""Условное равновесие пружины и заданного отбойника при вертикальной нагрузке.

Одномерная модель не рассчитывает контакт шины, прочие силы и устойчивость.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite
from typing import Literal

import numpy as np

from ..model.entities import Axle
from .damper import DamperMetrics, LowerArmDamper
from .double_wishbone import DoubleWishbone, KinematicsError, Pose
from .spring_characteristics import (
    BumpStopCharacteristic,
    BumpStopState,
    SpringCharacteristic,
    SpringState,
    bump_stop_state,
    spring_state,
)
from .springs import lower_arm_motion_ratio_at_pose, lower_arm_spring_length, spring_wheel_support
from .stroke import StrokeLimits
from .sweep import limited_sweep


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
    bump_stop: BumpStopState | None = None
    total_support_n: float | None = None
    damper: DamperMetrics | None = None
    pose: Pose | None = None


@dataclass(frozen=True)
class PathFailure:
    """Первый недоступный отсчёт и фактический ход отказа решателя."""

    requested_travel_mm: float
    failure_travel_mm: float
    kind: Literal["kinematics", "component", "branch_mismatch"]
    reason: str


@dataclass(frozen=True)
class EquilibriumPath:
    """Выборочные точки от нуля до цели, без гарантии между ними."""

    target_travel_mm: float
    requested_step_mm: float
    actual_step_mm: float
    samples: tuple[EquilibriumSample, ...]
    failure: PathFailure | None
    limitations: tuple[str, ...]

    @property
    def completed(self) -> bool:
        """Все запрошенные точки пройдены; это не гарантия непрерывного пути."""
        return self.failure is None


class EquilibriumPathError(EquilibriumError):
    """Проверка пути обнаружила конфликт; детали и пройденные точки сохранены."""

    def __init__(self, path: EquilibriumPath) -> None:
        if path.failure is None:
            raise ValueError("Ошибка пути должна содержать причину")
        self.path = path
        super().__init__(path.failure.failure_travel_mm, path.failure.reason)


@dataclass(frozen=True)
class EquilibriumResult:
    """Проверенный интервал и отдельно рассчитанная оценка его середины."""

    lower: EquilibriumSample
    upper: EquilibriumSample
    estimate: EquilibriumSample
    evaluations: int
    limitations: tuple[str, ...]
    path: EquilibriumPath | None = None


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
        bump_stop: BumpStopCharacteristic | None = None,
        damper_mount: Literal["lower_arm"] | None = None,
        damper_limits: StrokeLimits | None = None,
        max_step_mm: float = 2.0,
    ) -> None:
        if not isfinite(static_spring_length_mm) or static_spring_length_mm <= 0:
            raise ValueError("Статическая длина пружины должна быть положительной и конечной")
        if not isfinite(max_step_mm) or max_step_mm <= 0:
            raise ValueError("Шаг продолжения должен быть положительным и конечным")
        if damper_mount not in (None, "lower_arm"):
            raise ValueError("Неизвестный вариант крепления амортизатора")
        if damper_mount is None and damper_limits is not None:
            raise ValueError("Для проверки амортизатора требуется указать его крепление")
        self.model = DoubleWishbone(axle, side)
        self.damper = LowerArmDamper(self.model, axle) if damper_mount is not None else None
        self.damper_limits = damper_limits
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
        self.bump_stop = bump_stop
        self.max_step_mm = max_step_mm
        self.limitations = (
            "spring_length_change_equals_mount_distance_change",
            "spring_preload_not_applied",
            "spring_and_optional_bump_stop_only",
            "tire_contact_and_other_forces_not_modeled",
            "equilibrium_stability_not_checked",
            "continuous_reachable_branch_not_guaranteed",
        ) + (("spring_coil_bind_unspecified",) if coil_bind_length_mm is None else ())
        if self.damper is None:
            self.limitations += ("damper_mount_unspecified",)
        else:
            self.limitations += ("damper_lower_arm_mount_assumed", "damper_damping_force_not_modeled")
            self.limitations += (("damper_limits_unspecified",) if damper_limits is None else ("damper_limits_discrete_only",))
        if bump_stop is None:
            self.limitations += ("bump_stop_not_modeled",)
        else:
            self.limitations += ("bump_stop_constant_motion_ratio",)
            if bump_stop.max_compression_mm is None:
                self.limitations += ("bump_stop_max_compression_unspecified",)

    def evaluate(self, travel_mm: float, load_n: float) -> EquilibriumSample:
        """Рассчитывает локальное условие баланса для заданной силы в Н."""
        if not isfinite(load_n) or load_n <= 0:
            raise ValueError("Нагрузка на колесо должна быть положительной и конечной")
        pose = self.model.solve(travel_mm, max_step_mm=self.max_step_mm)
        return self._evaluate_pose(pose, load_n)

    def _evaluate_pose(self, pose: Pose, load_n: float) -> EquilibriumSample:
        travel_mm = pose.travel_mm
        damper = self.damper.evaluate(pose, self.damper_limits) if self.damper is not None else None
        if damper is not None and damper.has_detected_conflict:
            reason = damper.error or (damper.stroke.status if damper.stroke is not None else "неизвестная ошибка")
            raise EquilibriumError(travel_mm, f"недопустимое положение амортизатора: {reason}")
        distance = lower_arm_spring_length(self.model, pose, self.lower, self.upper)
        length = self.static_spring_length_mm + (distance - self.initial_mount_length)
        if not isfinite(length) or length <= 0:
            raise EquilibriumError(travel_mm, "неположительная или неконечная длина пружины")
        state = spring_state(self.characteristic, length)
        if state.force_n is None:
            raise EquilibriumError(travel_mm, f"неопределённая сила пружины: {state.status}")
        ratio = lower_arm_motion_ratio_at_pose(self.model, pose, self.lower, self.upper)
        support = spring_wheel_support(state.force_n, ratio)
        bump = bump_stop_state(self.bump_stop, travel_mm) if self.bump_stop is not None else None
        if bump is not None and bump.wheel_force_n is None:
            raise EquilibriumError(travel_mm, f"неопределённая сила отбойника: {bump.status}")
        total = support + (bump.wheel_force_n if bump is not None and bump.wheel_force_n is not None else 0.0)
        residual = total - load_n
        if not isfinite(total) or not isfinite(residual):
            raise EquilibriumError(travel_mm, "суммарная сила или невязка не является конечной")
        return EquilibriumSample(travel_mm, state, ratio, support, residual, bump, total, damper, pose)

    def check_path(self, target_travel_mm: float, load_n: float, *, step_mm: float) -> EquilibriumPath:
        """Выборочно проверяет известные ограничения от 0 до заданного хода.

        Шаг относится к точкам контроля, внутренний шаг решения может быть
        меньше. Неизвестные характеристики и препятствия между точками не
        становятся проверенными; полный путь и безопасность не гарантируются.
        """
        if not all(isfinite(v) for v in (target_travel_mm, load_n, step_mm)) or load_n <= 0 or step_mm <= 0:
            raise ValueError("Ход, нагрузка и шаг должны быть конечными, нагрузка и шаг — положительными")
        steps_float = abs(target_travel_mm) / step_mm
        if not isfinite(steps_float) or steps_float > 5000:
            raise ValueError("Слишком много точек проверки пути; увеличьте шаг")
        count = ceil(steps_float)
        travels = [0.0] if count == 0 else np.linspace(0, target_travel_mm, count + 1).tolist()
        sweep = limited_sweep(self.model, travels, self.max_step_mm)
        samples: list[EquilibriumSample] = []
        failure = None
        for point in sweep.points:
            if point.pose is None:
                if point.error is None:
                    raise RuntimeError("Отсутствует причина отказа кинематики")
                failure = PathFailure(point.travel_mm, point.error.travel_mm, "kinematics", point.error.reason)
                break
            try:
                samples.append(self._evaluate_pose(point.pose, load_n))
            except KinematicsError as exc:
                failure = PathFailure(point.travel_mm, exc.travel_mm, "kinematics", exc.reason)
                break
            except EquilibriumError as exc:
                failure = PathFailure(point.travel_mm, exc.travel_mm, "component", exc.reason)
                break
            except ValueError as exc:
                failure = PathFailure(point.travel_mm, point.travel_mm, "component", str(exc))
                break
        return EquilibriumPath(target_travel_mm, step_mm, abs(target_travel_mm) / count if count else 0.0,
                               tuple(samples), failure, self.limitations + ("path_sampled_only",))

    def find(
        self,
        load_n: float,
        from_travel_mm: float,
        to_travel_mm: float,
        *,
        travel_tolerance_mm: float = 0.01,
        path_step_mm: float | None = None,
    ) -> EquilibriumResult:
        """Уточняет один интервал смены знака методом бисекции.

        Не находит все решения и не гарантирует непрерывность непроверенных
        частей интервала. Численные или физические ошибки в оценённых точках
        прерывают поиск. Упоры амортизатора проверяются только при явном
        указании крепления и границ и лишь в вычисленных точках. Допуск
        относится к ширине интервала, не силе. При path_step_mm дополнительно
        проверяются заданные компоненты на выборке от статики до оценки корня.
        """
        if path_step_mm is not None and (not isfinite(path_step_mm) or path_step_mm <= 0):
            raise ValueError("Шаг проверки пути должен быть положительным и конечным")
        if not all(isfinite(v) for v in (load_n, from_travel_mm, to_travel_mm, travel_tolerance_mm)):
            raise ValueError("Нагрузка, границы и допуск должны быть конечными")
        if load_n <= 0 or from_travel_mm >= to_travel_mm or travel_tolerance_mm <= 0:
            raise ValueError("Нагрузка и допуск должны быть положительными, границы — возрастать")
        def finish(lower: EquilibriumSample, upper: EquilibriumSample, estimate: EquilibriumSample, count: int) -> EquilibriumResult:
            if path_step_mm is None:
                return EquilibriumResult(lower, upper, estimate, count, self.limitations + ("equilibrium_path_not_checked",))
            path = self.check_path(estimate.travel_mm, load_n, step_mm=path_step_mm)
            if path.failure is not None:
                raise EquilibriumPathError(path)
            endpoint = path.samples[-1]
            if (endpoint.pose is None or estimate.pose is None
                    or not np.allclose(endpoint.pose.center, estimate.pose.center, rtol=0, atol=1e-6)
                    or not np.allclose(endpoint.pose.rotation, estimate.pose.rotation, rtol=0, atol=1e-8)):
                mismatch = PathFailure(estimate.travel_mm, estimate.travel_mm, "branch_mismatch",
                                       "ветвь решения в конце проверки пути не совпадает с найденной")
                raise EquilibriumPathError(EquilibriumPath(path.target_travel_mm, path.requested_step_mm,
                                                          path.actual_step_mm, path.samples, mismatch, path.limitations))
            return EquilibriumResult(lower, upper, estimate, count, path.limitations, path)

        lower = self.evaluate(from_travel_mm, load_n)
        upper = self.evaluate(to_travel_mm, load_n)
        count = 2
        if lower.residual_n == 0:
            return finish(lower, lower, lower, count)
        if upper.residual_n == 0:
            return finish(upper, upper, upper, count)
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
                return finish(middle, middle, middle, count)
            if (middle.residual_n > 0) == (lower.residual_n > 0):
                lower = middle
            else:
                upper = middle
        if upper.travel_mm - lower.travel_mm > travel_tolerance_mm:
            raise ValueError("Не удалось уточнить ход до заданного допуска")
        estimate_travel = lower.travel_mm + (upper.travel_mm - lower.travel_mm) / 2
        estimate = self.evaluate(estimate_travel, load_n)
        return finish(lower, upper, estimate, count + 1)


@dataclass(frozen=True)
class SpringSupportTangent:
    """Локальная оценка производной силы с геометрическим вкладом, Н/мм."""

    travel_mm: float
    step_mm: float
    elastic_component_n_mm: float
    geometric_component_n_mm: float
    total_n_mm: float
    direct_difference_n_mm: float


def estimate_spring_support_tangent(
    problem: SpringEquilibrium,
    travel_mm: float,
    *,
    step_mm: float = 0.01,
) -> SpringSupportTangent:
    """Оценивает d(F_пруж·MR)/dh центральной разностью изменения MR.

    Возвращаются упругий и геометрический вклады, а также независимая от
    разложения конечная разность силы только пружины для контроля шага. Даже
    при наличии отбойника его вклад здесь не включается. Выявленные
    в трёх точках контактные границы и изломы характеристики не допускаются;
    непрерывность между ними при конечном шаге не доказывается. Другие силы,
    контакт шины и устойчивость автомобиля не оцениваются.
    """
    if not isfinite(travel_mm) or not isfinite(step_mm) or step_mm <= 0:
        raise ValueError("Ход и шаг должны быть конечными, шаг — положительным")
    low_travel, high_travel = travel_mm - step_mm, travel_mm + step_mm
    if not isfinite(low_travel) or not isfinite(high_travel) or not low_travel < travel_mm < high_travel:
        raise ValueError("Шаг слишком мал или велик для заданного хода")
    # Нагрузка не влияет на силу и используется только для невязки evaluate.
    low = problem.evaluate(low_travel, 1.0)
    center = problem.evaluate(travel_mm, 1.0)
    high = problem.evaluate(high_travel, 1.0)
    if any(sample.spring.status != "loaded" for sample in (low, center, high)):
        raise EquilibriumError(travel_mm, "жёсткость не определена вне нагруженного участка пружины")
    curve = problem.characteristic.progressive
    if curve:
        def segment(sample: EquilibriumSample) -> int | None:
            for i, (a, b) in enumerate(zip(curve, curve[1:], strict=False)):
                if a[0] < sample.spring.compression_mm < b[0]:
                    return i
            return None

        indices = {segment(sample) for sample in (low, center, high)}
        if None in indices or len(indices) != 1:
            raise EquilibriumError(travel_mm, "расчётный шаг пересекает излом характеристики")
    rate, force = center.spring.tangent_rate_n_mm, center.spring.force_n
    if rate is None or force is None:
        raise EquilibriumError(travel_mm, "сила или жёсткость пружины не определена")
    elastic = rate * center.motion_ratio**2
    geometric = force * (high.motion_ratio - low.motion_ratio) / (2 * step_mm)
    total = elastic + geometric
    direct = (high.wheel_support_n - low.wheel_support_n) / (2 * step_mm)
    if not all(isfinite(value) for value in (elastic, geometric, total, direct)):
        raise EquilibriumError(travel_mm, "жёсткость не является конечной")
    return SpringSupportTangent(travel_mm, step_mm, elastic, geometric, total, direct)
