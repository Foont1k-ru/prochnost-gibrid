"""Геометрические точки для визуализации одной рассчитанной двухрычажной стороны."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model.entities import Axle
from .double_wishbone import DoubleWishbone, Pose
from .springs import lower_arm_point

Point = tuple[float, float, float]


def _point(v: np.ndarray) -> Point:
    return float(v[0]), float(v[1]), float(v[2])


@dataclass(frozen=True)
class PoseView:
    """Точки в ISO, координаты опор и перемещённых шаровых в мм."""

    travel_mm: float
    center: Point
    upper_front: Point
    upper_rear: Point
    lower_front: Point
    lower_rear: Point
    upper_ball: Point
    lower_ball: Point
    spring: tuple[Point, Point] | None
    damper: tuple[Point, Point] | None


def pose_view(model: DoubleWishbone, pose: Pose, axle: Axle, *, spring: bool, damper: bool) -> PoseView:
    """Из тех же положений решателя строит опоры для схематической проекции.

    Пружина/амортизатор рисуются только при явном допущении крепления:
    низ жёстко на нижнем рычаге, верх на кузове. Проекция не является
    доказательством того, что положение механически допустимо.
    """
    def element(prefix: str) -> tuple[Point, Point]:
        low, high = axle.hardpoints[prefix + "_lo"], axle.hardpoints[prefix + "_up"]
        p = np.array([low.x, low.y * model.sign, low.z], dtype=float)
        q = np.array([high.x, high.y * model.sign, high.z], dtype=float)
        if not np.all(np.isfinite(p)) or not np.all(np.isfinite(q)):
            raise ValueError("Координаты элемента должны быть конечными")
        return _point(lower_arm_point(model, pose, p)), _point(q)

    return PoseView(
        pose.travel_mm, _point(pose.center),
        _point(model.points["uca_f_in"]), _point(model.points["uca_r_in"]),
        _point(model.points["lca_f_in"]), _point(model.points["lca_r_in"]),
        _point(pose.point(model.points["ubj"], model.center0)),
        _point(pose.point(model.points["lbj"], model.center0)),
        element("spring") if spring else None, element("damper") if damper else None,
    )
