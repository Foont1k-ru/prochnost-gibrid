"""Трёхмерная кинематика двухрычажной подвески с неподвижной рейкой.

Кулак — твёрдое тело. Две шаровые удерживаются каждая на окружности
качания А-рычага, наружный шарнир рулевой тяги — на сфере постоянного
радиуса, высота центра колеса задаётся ходом. Продолжение начинается
в исходном положении и выполняется малыми шагами; при сингулярности или
потере сходимости результат не подменяется приближённым решением.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial.transform import Rotation

from ..model.entities import Axle

Array = NDArray[np.float64]
MAX_CONTINUATION_STEPS = 20_000
_REQUIRED = ("uca_f_in", "uca_r_in", "ubj", "lca_f_in", "lca_r_in", "lbj", "tierod_in", "tierod_out", "wheel_center")


def validate_sweep_input(travels_mm: list[float], max_step_mm: float) -> None:
    """Ограничивает объём продолжения до начала выделения памяти и вычислений."""
    if not np.isfinite(max_step_mm) or max_step_mm <= 0 or not all(np.isfinite(t) for t in travels_mm):
        raise ValueError("Ходы и шаг должны быть конечными, шаг должен быть положительным")
    if len(travels_mm) > MAX_CONTINUATION_STEPS:
        raise ValueError("Слишком много точек свипа")
    positive = max((t for t in travels_mm if t > 0), default=0.0)
    negative = min((t for t in travels_mm if t < 0), default=0.0)
    if (positive / max_step_mm + abs(negative) / max_step_mm + len(set(travels_mm))) > MAX_CONTINUATION_STEPS:
        raise ValueError("Слишком много шагов продолжения; увеличьте шаг или уменьшите диапазон")


class KinematicsError(ValueError):
    """Недопустимая или несобираемая геометрия с указанием хода."""

    def __init__(self, travel_mm: float, reason: str) -> None:
        self.travel_mm = travel_mm
        self.reason = reason
        super().__init__(f"Не удалось решить подвеску при ходе {travel_mm:+.3f} мм: {reason}")


@dataclass(frozen=True)
class Pose:
    """Положение кулака; матрица вращения действует на исходные координаты."""

    travel_mm: float
    center: Array
    rotation: Array
    condition: float
    residual_mm: float

    def point(self, initial_point: Array, initial_center: Array) -> Array:
        """Перемещает точку, жёстко связанную с кулаком."""
        return self.center + self.rotation @ (initial_point - initial_center)


class DoubleWishbone:
    """Пять жёстких связей кулака и заданный вертикальный ход колеса."""

    def __init__(self, axle: Axle, side: str = "left") -> None:
        if axle.type_code != "double_wishbone":
            raise ValueError("Требуется двухрычажная подвеска")
        if side not in ("left", "right"):
            raise ValueError("Сторона должна быть left или right")
        self.side = side
        self.sign = 1.0 if side == "left" else -1.0
        try:
            self.points = {
                code: np.array((axle.hardpoints[code].x, self.sign * axle.hardpoints[code].y, axle.hardpoints[code].z), dtype=float)
                for code in _REQUIRED
            }
        except KeyError as error:
            raise KinematicsError(0, f"отсутствует точка {error.args[0]}") from error
        if not all(np.all(np.isfinite(point)) for point in self.points.values()):
            raise KinematicsError(0, "координаты должны быть конечными числами")
        self.center0 = self.points["wheel_center"].copy()
        self._pairs = (
            ("ubj", "uca_f_in"), ("ubj", "uca_r_in"),
            ("lbj", "lca_f_in"), ("lbj", "lca_r_in"), ("tierod_out", "tierod_in"),
        )
        self._local = np.stack([self.points[moving] - self.center0 for moving, _ in self._pairs])
        self._fixed = np.stack([self.points[fixed] for _, fixed in self._pairs])
        self._lengths = np.linalg.norm(self._local + self.center0 - self._fixed, axis=1)
        if np.any(self._lengths < 1e-6):
            raise KinematicsError(0, "совпадают шарниры связи")
        for a, b in (("uca_f_in", "uca_r_in"), ("lca_f_in", "lca_r_in")):
            if np.linalg.norm(self.points[a] - self.points[b]) < 1e-6:
                raise KinematicsError(0, "внутренние точки оси рычага совпадают")
        if np.linalg.norm(self.points["ubj"] - self.points["lbj"]) < 1e-6:
            raise KinematicsError(0, "верхняя и нижняя шаровые совпадают")
        _, jac = self._system(self.center0, np.eye(3), 0.0)
        self._condition(jac, 0.0)

    @staticmethod
    def _condition(jac: Array, travel: float) -> float:
        """Контролирует ранг нормированного якобиана, а не только невязку."""
        scaled = jac.copy()
        scaled[:, 3:] /= 100.0
        cond = float(np.linalg.cond(scaled))
        if not np.isfinite(cond) or cond > 1e8:
            raise KinematicsError(travel, "геометрия вырождена или близка к сингулярности")
        return cond

    def _system(self, center: Array, rotation: Array, travel: float) -> tuple[Array, Array]:
        """Невязка и аналитический якобиан по локальному винтовому приращению."""
        arms = (rotation @ self._local.T).T
        delta = center + arms - self._fixed
        residual = np.empty(6)
        residual[:5] = (np.einsum("ij,ij->i", delta, delta) - self._lengths**2) / (2 * self._lengths)
        residual[5] = center[2] - self.center0[2] - travel
        jac = np.zeros((6, 6))
        jac[:5, :3] = delta / self._lengths[:, None]
        jac[:5, 3] = (arms[:, 1] * delta[:, 2] - arms[:, 2] * delta[:, 1]) / self._lengths
        jac[:5, 4] = (arms[:, 2] * delta[:, 0] - arms[:, 0] * delta[:, 2]) / self._lengths
        jac[:5, 5] = (arms[:, 0] * delta[:, 1] - arms[:, 1] * delta[:, 0]) / self._lengths
        jac[5, 2] = 1.0
        return residual, jac

    def _residual(self, center: Array, rotation: Array, travel: float) -> Array:
        """Невязки без вычисления якобиана для поиска длины шага."""
        delta = center + (rotation @ self._local.T).T - self._fixed
        residual = np.empty(6)
        residual[:5] = (np.einsum("ij,ij->i", delta, delta) - self._lengths**2) / (2 * self._lengths)
        residual[5] = center[2] - self.center0[2] - travel
        return residual

    def initial_pose(self) -> Pose:
        """Исходная геометрия при нулевом ходе."""
        _, jac = self._system(self.center0, np.eye(3), 0.0)
        return Pose(0.0, self.center0.copy(), np.eye(3), self._condition(jac, 0.0), 0.0)

    def _step(self, previous: Pose, travel: float) -> Pose:
        """Один шаг Ньютона с аналитическим якобианом и поиском длины шага."""
        center = previous.center.copy()
        rotation = previous.rotation.copy()
        for _ in range(30):
            residual, jac = self._system(center, rotation, travel)
            condition = self._condition(jac, travel)
            error = float(np.max(np.abs(residual)))
            if error < 1e-8:
                angle = float(np.linalg.norm(Rotation.from_matrix(rotation @ previous.rotation.T).as_rotvec()))
                if np.linalg.norm(center - previous.center) > 30 or angle > 0.25:
                    raise KinematicsError(travel, "скачок решения между ветвями")
                return Pose(travel, center, rotation, condition, error)
            try:
                change = np.linalg.solve(jac, -residual)
            except np.linalg.LinAlgError as exc:
                raise KinematicsError(travel, "якобиан вырожден") from exc
            accepted = False
            for power in range(12):
                alpha = 0.5**power
                new_center = center + alpha * change[:3]
                new_rotation = Rotation.from_rotvec(alpha * change[3:]).as_matrix() @ rotation
                new_residual = self._residual(new_center, new_rotation, travel)
                if np.linalg.norm(new_residual) < np.linalg.norm(residual):
                    center, rotation = new_center, new_rotation
                    accepted = True
                    break
            if not accepted:
                raise KinematicsError(travel, "решение ограничений не сходится")
        raise KinematicsError(travel, "превышено число итераций решателя")

    def solve(self, travel_mm: float, max_step_mm: float = 2.0) -> Pose:
        """Решает положение, продолжая статическую ветвь с ограничением шага."""
        validate_sweep_input([travel_mm], max_step_mm)
        pose = self.initial_pose()
        count = max(1, int(np.ceil(abs(travel_mm) / max_step_mm)))
        for target in np.linspace(0.0, travel_mm, count + 1)[1:]:
            pose = self._step(pose, float(target))
        return pose

    def sweep(self, travels_mm: list[float], max_step_mm: float = 2.0) -> list[Pose]:
        """Решает независимые ветви сжатия и отбоя с тёплым стартом от статики."""
        validate_sweep_input(travels_mm, max_step_mm)
        result: dict[float, Pose] = {0.0: self.initial_pose()}
        for sign in (1, -1):
            pose = result[0.0]
            values = sorted({float(t) for t in travels_mm if t * sign > 0}, key=abs)
            for target in values:
                count = max(1, int(np.ceil(abs(target - pose.travel_mm) / max_step_mm)))
                for value in np.linspace(pose.travel_mm, target, count + 1)[1:]:
                    pose = self._step(pose, float(value))
                result[target] = pose
        return [result[float(t)] for t in travels_mm]
