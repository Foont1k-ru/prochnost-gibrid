"""Кинематика амортизатора с нижним креплением на А-рычаге."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model.entities import Axle
from .double_wishbone import DoubleWishbone, Pose
from .springs import lower_arm_motion_ratio_at_pose, lower_arm_spring_length
from .stroke import StrokeLimits, StrokeState, stroke_state


@dataclass(frozen=True)
class DamperMetrics:
    """Изменение длины и запасы амортизатора; неизвестные упоры не проверены."""

    length_mm: float
    compression_from_static_mm: float
    motion_ratio: float | None
    stroke: StrokeState | None
    error: str | None = None

    @property
    def has_detected_conflict(self) -> bool:
        """Состояние на известном упоре или за ним, либо совпадение опор."""
        return self.error is not None or (self.stroke is not None and self.stroke.status != "inside")


class LowerArmDamper:
    """Нижняя опора на рычаге, верхняя на кузове, координаты оси зеркалируются."""

    def __init__(self, model: DoubleWishbone, axle: Axle) -> None:
        self.model = model
        try:
            p, q = axle.hardpoints["damper_lo"], axle.hardpoints["damper_up"]
        except KeyError as exc:
            raise ValueError("Не заданы опоры амортизатора") from exc
        self.lower = np.array([p.x, p.y * model.sign, p.z], dtype=float)
        self.upper = np.array([q.x, q.y * model.sign, q.z], dtype=float)
        if not np.all(np.isfinite(self.lower)) or not np.all(np.isfinite(self.upper)):
            raise ValueError("Координаты опор амортизатора должны быть конечными")
        self.initial_length_mm = lower_arm_spring_length(model, model.initial_pose(), self.lower, self.upper)
        if self.initial_length_mm <= 1e-9:
            raise ValueError("Опоры амортизатора совпадают")

    def evaluate(self, pose: Pose, limits: StrokeLimits | None = None) -> DamperMetrics:
        """Проверяет только переданное положение; геометрический ход не ограничивает."""
        length = lower_arm_spring_length(self.model, pose, self.lower, self.upper)
        compression = self.initial_length_mm - length
        if length <= 1e-9:
            return DamperMetrics(length, compression, None, None, "Опоры амортизатора совпадают")
        ratio = lower_arm_motion_ratio_at_pose(self.model, pose, self.lower, self.upper)
        stroke = stroke_state(length, limits) if limits is not None else None
        return DamperMetrics(length, compression, ratio, stroke)
