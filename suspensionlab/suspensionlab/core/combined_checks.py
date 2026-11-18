"""Дискретные проверки компонентов по тем же позам, что и стабилизатор."""
from __future__ import annotations

from dataclasses import dataclass
from math import dist, isfinite
from typing import Literal

from .pose_view import PoseView
from .stroke import StrokeLimits, StrokeState, stroke_state


@dataclass(frozen=True)
class ComponentCheckOptions:
    """Явные данные для обеих сторон; None означает, что предел неизвестен."""

    static_spring_length_mm: float | None = None
    coil_bind_length_mm: float | None = None
    damper_limits: StrokeLimits | None = None

    def __post_init__(self) -> None:
        for value in (self.static_spring_length_mm, self.coil_bind_length_mm):
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError("Длины пружины должны быть положительными и конечными")
        if self.coil_bind_length_mm is not None and self.static_spring_length_mm is None:
            raise ValueError("Для проверки смыкания нужна длина пружины в статике")


@dataclass(frozen=True)
class SpringClearance:
    length_mm: float | None
    coil_clearance_mm: float | None
    status: Literal["length_unknown", "limit_unknown", "clear", "coil_bind", "invalid"]


@dataclass(frozen=True)
class DamperClearance:
    length_mm: float
    stroke: StrokeState | None
    invalid: bool = False


@dataclass(frozen=True)
class ComponentChecks:
    """Отсутствующий объект означает, что соответствующее крепление не задано."""

    spring: SpringClearance | None
    damper: DamperClearance | None


def check_components(frame: PoseView, static: PoseView, options: ComponentCheckOptions) -> ComponentChecks:
    """Проверяет только данное положение, не останавливая кинематику на упорах.

    Предполагается изменение длины пружины, равное изменению расстояния опор.
    Фактическая длина в статике задаётся отдельно, а не выводится из опор.
    """
    spring = None
    if frame.spring is not None:
        if static.spring is None:
            raise ValueError("Не заданы статические опоры пружины")
        current_distance = dist(*frame.spring)
        initial_distance = dist(*static.spring)
        if not all(isfinite(x) and x > 1e-9 for x in (current_distance, initial_distance)):
            spring = SpringClearance(None, None, "invalid")
        elif options.static_spring_length_mm is None:
            spring = SpringClearance(None, None, "length_unknown")
        else:
            length = options.static_spring_length_mm + (current_distance - initial_distance)
            if not isfinite(length) or length <= 0:
                spring = SpringClearance(None, None, "invalid")
            elif options.coil_bind_length_mm is None:
                spring = SpringClearance(length, None, "limit_unknown")
            else:
                clearance = length - options.coil_bind_length_mm
                spring = SpringClearance(length, clearance, "coil_bind" if clearance <= 0 else "clear")
    damper = None
    if frame.damper is not None:
        length = dist(*frame.damper)
        if not isfinite(length) or length <= 1e-9:
            damper = DamperClearance(length, None, True)
        else:
            damper = DamperClearance(length, stroke_state(length, options.damper_limits)
                                     if options.damper_limits is not None else None)
    return ComponentChecks(spring, damper)
