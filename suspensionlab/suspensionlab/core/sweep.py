"""Свип хода с сохранением достигнутого диапазона и причин отказа."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite

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


def travel_grid(from_mm: float, to_mm: float, *, max_spacing_mm: float = 1.0) -> list[float]:
    """Равномерная сетка, содержащая границы и ноль при пересечении статики.

    Меньшая сетка не гарантирует обнаружения узких конфликтов между отсчётами.
    """
    if not all(isfinite(x) for x in (from_mm, to_mm, max_spacing_mm)) or max_spacing_mm <= 0 or from_mm > to_mm:
        raise ValueError("Границы должны быть конечными и возрастать, шаг — положительным")
    boundaries = [from_mm, 0.0, to_mm] if from_mm < 0 < to_mm else [from_mm, to_mm]
    intervals = []
    for a, b in zip(boundaries, boundaries[1:], strict=False):
        steps = (b - a) / max_spacing_mm
        if not isfinite(steps) or steps > 5000:
            raise ValueError("Слишком много точек свипа; увеличьте шаг")
        intervals.append(ceil(steps))
    if sum(intervals) + 1 > 5000:
        raise ValueError("Слишком много точек свипа; увеличьте шаг")
    result = [from_mm]
    for (a, b), count in zip(zip(boundaries, boundaries[1:], strict=False), intervals, strict=True):
        for i in range(1, count + 1):
            result.append(b if i == count else a + (b - a) * i / count)
    if any(a >= b for a, b in zip(result, result[1:], strict=False)):
        raise ValueError("Шаг слишком мал для точности чисел на заданном диапазоне")
    return result


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
