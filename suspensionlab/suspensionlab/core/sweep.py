"""Свип хода с сохранением достигнутого диапазона и причин отказа."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from .double_wishbone import DoubleWishbone, KinematicsError, Pose, validate_sweep_input


@dataclass(frozen=True)
class SweepPoint:
    """Для каждой заданной точки возвращается решение или причина отказа."""

    travel_mm: float
    pose: Pose | None
    error: KinematicsError | None


@dataclass(frozen=True)
class LimitedSweep:
    """Результаты в порядке запроса и фактически достигнутые концы ветвей."""

    points: tuple[SweepPoint, ...]
    reachable_droop_mm: float
    reachable_bump_mm: float


def limited_sweep(model: DoubleWishbone, travels_mm: list[float], max_step_mm: float = 2.0) -> LimitedSweep:
    """Продолжает обе ветви от статики, сохраняя точки до первого отказа.

    Границы — последние успешно решённые численные шаги, не доказанные
    геометрические пределы. После первого отказа ветвь не экстраполируется.
    """
    validate_sweep_input(travels_mm, max_step_mm)
    initial = model.initial_pose()
    results = {0.0: SweepPoint(0.0, initial, None)}
    bounds = {1: 0.0, -1: 0.0}
    for sign in (1, -1):
        pose = initial
        failure: KinematicsError | None = None
        targets = sorted({float(t) for t in travels_mm if sign * t > 0}, key=abs)
        for target in targets:
            if failure is None:
                begin = pose.travel_mm
                steps = max(1, ceil(abs(target - begin) / max_step_mm))
                for i in range(1, steps + 1):
                    step_target = begin + (target - begin) * i / steps
                    try:
                        pose = model._step(pose, step_target)
                    except KinematicsError as error:
                        failure = error
                        break
                    bounds[sign] = pose.travel_mm
            results[target] = SweepPoint(target, pose if failure is None else None, failure)
    return LimitedSweep(tuple(results[float(t)] for t in travels_mm), bounds[-1], bounds[1])
