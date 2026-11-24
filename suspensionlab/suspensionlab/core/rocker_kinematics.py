"""Экспериментальная геометрия одного жёсткого коромысла и тяги.

Ядро вызывается экспериментальным API для поз подвески и рабочей областью.
Нет сил, упругости, столкновений или проверки непрерывного движения.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import acos, atan2, cos, dist, hypot, isfinite, pi, sin, sqrt

Point = tuple[float, float, float]


class RockerError(ValueError):
    """Геометрия не определена или положение тяги недостижимо."""


def _point(value: Point) -> Point:
    try:
        if len(value) != 3 or any(isinstance(v, bool) or not isfinite(v) or abs(v) > 1_000_000 for v in value):
            raise RockerError('invalid point')
        return float(value[0]), float(value[1]), float(value[2])
    except (TypeError, OverflowError) as exc:
        raise RockerError('invalid point') from exc


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _mul(a: Point, s: float) -> Point:
    return a[0] * s, a[1] * s, a[2] * s


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Point, b: Point) -> Point:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _norm(a: Point) -> float:
    return sqrt(_dot(a, a))


def _rotate(v: Point, axis: Point, angle: float) -> Point:
    parallel = _mul(axis, _dot(v, axis))
    radial = _sub(v, parallel)
    return _add(parallel, _add(_mul(radial, cos(angle)), _mul(_cross(axis, radial), sin(angle))))


@dataclass(frozen=True, slots=True)
class RockerGeometry:
    """Исходные центры в мм, ось зафиксирована на неподвижном кузове.

    Родоначальная длина тяги берётся из исходных шарниров, не является
    рекомендацией. При симметрии отражение геометрии задаёт вызывающий код.
    """
    pivot: Point
    axis: Point
    rod_rocker: Point
    rod_suspension: Point
    damper_rocker: Point
    damper_body: Point

    def __post_init__(self) -> None:
        for name in ('pivot', 'axis', 'rod_rocker', 'rod_suspension', 'damper_rocker', 'damper_body'):
            object.__setattr__(self, name, _point(getattr(self, name)))
        axis_length = _norm(self.axis)
        if axis_length < 1e-9:
            raise RockerError('zero rocker axis')
        unit = _mul(self.axis, 1 / axis_length)
        object.__setattr__(self, 'axis', unit)
        for p in (self.rod_rocker, self.damper_rocker):
            vector = _sub(p, self.pivot)
            if _norm(_sub(vector, _mul(unit, _dot(vector, unit)))) < 1e-9:
                raise RockerError('rocker attachment on axis')
        if dist(self.rod_rocker, self.rod_suspension) < 1e-9:
            raise RockerError('zero rod length')
        if dist(self.damper_rocker, self.damper_body) < 1e-9:
            raise RockerError('zero damper length')

    @property
    def rod_length(self) -> float:
        return dist(self.rod_rocker, self.rod_suspension)


@dataclass(frozen=True, slots=True)
class RockerPose:
    angle_rad: float
    rod_rocker: Point
    damper_rocker: Point
    damper_length_mm: float


def solve_rocker(geometry: RockerGeometry, rod_suspension: Point, *, previous_angle_rad: float = 0.0) -> RockerPose:
    """Выбрать ближайшую к предыдущему углу ветвь при заданном шарнире тяги.

    Соседние рассчитанные позы не доказывают непрерывную достижимость между
    ними. Касание ветвей и произвольное вращение вокруг оси отклоняются как
    неоднозначные; выход за геометрию вызывает RockerError, без старой позы.
    """
    if (type(previous_angle_rad) not in (int, float) or not isfinite(previous_angle_rad)
            or abs(previous_angle_rad) > 1e6):
        raise RockerError('invalid previous angle')
    target = _point(rod_suspension)
    vector = _sub(geometry.rod_rocker, geometry.pivot)
    parallel = _mul(geometry.axis, _dot(vector, geometry.axis))
    radial = _sub(vector, parallel)
    cross = _cross(geometry.axis, radial)
    q = _sub(_add(geometry.pivot, parallel), target)
    a, b = _dot(q, radial), _dot(q, cross)
    amplitude = hypot(a, b)
    if amplitude < 1e-12:
        raise RockerError('undetermined or unreachable rocker angle')
    c = (geometry.rod_length ** 2 - _dot(q, q) - _dot(radial, radial)) / 2
    ratio = c / amplitude
    if not isfinite(ratio) or abs(ratio) >= 1 - 1e-10:
        raise RockerError('unreachable or ambiguous rocker angle')
    phase = atan2(b, a)
    delta = acos(ratio)
    candidates = (phase + delta, phase - delta)
    angles = [angle + 2 * pi * round((previous_angle_rad - angle) / (2 * pi)) for angle in candidates]
    distances = [abs(angle - previous_angle_rad) for angle in angles]
    if abs(distances[0] - distances[1]) < 1e-10:
        raise RockerError('ambiguous rocker branch')
    angle = angles[0] if distances[0] < distances[1] else angles[1]
    rod = _add(geometry.pivot, _rotate(vector, geometry.axis, angle))
    damper = _add(geometry.pivot, _rotate(_sub(geometry.damper_rocker, geometry.pivot), geometry.axis, angle))
    length = dist(damper, geometry.damper_body)
    if not isfinite(length) or length < 1e-9:
        raise RockerError('invalid damper length')
    return RockerPose(angle, rod, damper, length)


@dataclass(frozen=True, slots=True)
class RockerInput:
    """Заданная дискретная поза; None означает отсутствие решения подвески."""
    travel_mm: float
    rod_suspension: Point | None


@dataclass(frozen=True, slots=True)
class RockerSample:
    """Только численное решение на сетке, а не проверка непрерывного хода."""
    travel_mm: float
    pose: RockerPose | None
    error: str | None
    motion_ratio: float | None = None


def solve_rocker_sweep(geometry: RockerGeometry, inputs: Sequence[RockerInput], *,
                       max_step_mm: float = 2.0, max_angle_step_rad: float = pi / 3) -> tuple[RockerSample, ...]:
    """Продолжить две ветви от исходной точки без перескока через отказ.

    Вход отсортирован по ходу, содержит ровно один ноль, расстояния соседних
    положений не более 2 мм. Это дискретное слежение за ближайшей ветвью, не
    доказательство её непрерывности: между отсчётами конфликты не проверяются.
    Слишком большой скачок угла и неоднозначные положения останавливают только
    соответствующую ветвь. Положение в нуле должно соответствовать исходным
    центрам, иначе новая геометрия не принимается как исходная сборка.

    Передаточное отношение — приближённое -dL/dh, вычисленное по двум соседним
    решённым положениям. На границах, у отказа и без соседей оно не определено.
    Это не передаточное отношение силы и не расчёт жёсткости или безопасности.
    """
    if (type(max_step_mm) not in (int, float) or not isfinite(max_step_mm) or
            not 0 < max_step_mm <= 2.0 or type(max_angle_step_rad) not in (int, float) or
            not isfinite(max_angle_step_rad) or not 0 < max_angle_step_rad <= pi / 2):
        raise RockerError('invalid continuation step')
    if not inputs or len(inputs) > 5000 or any(not isinstance(item, RockerInput) for item in inputs):
        raise RockerError('invalid or oversized rocker sweep')
    travels = [item.travel_mm for item in inputs]
    if any(type(t) not in (int, float) or not isfinite(t) or abs(t) > 1_000_000 for t in travels):
        raise RockerError('invalid travel')
    if (travels.count(0) != 1 or any(not 0 < b - a <= max_step_mm + 1e-9
                                     for a, b in zip(travels, travels[1:], strict=False))):
        raise RockerError('rocker sweep needs ordered dense samples and one zero')
    zero = travels.index(0)
    output: list[RockerSample | None] = [None] * len(inputs)
    try:
        source = inputs[zero].rod_suspension
        if source is None:
            raise RockerError('no suspension pose at zero')
        source = _point(source)
        if dist(source, geometry.rod_suspension) > 1e-5:
            raise RockerError('zero pose differs from rocker reference')
        initial = solve_rocker(geometry, source)
        if abs(initial.angle_rad) > 1e-8:
            raise RockerError('zero pose does not match reference branch')
        output[zero] = RockerSample(0.0, initial, None)
    except RockerError as error:
        message = str(error)
        return tuple(RockerSample(item.travel_mm, None, message if i == zero else
                                  'not evaluated: zero rocker pose failed') for i, item in enumerate(inputs))

    for indices in (range(zero + 1, len(inputs)), range(zero - 1, -1, -1)):
        previous = initial.angle_rad
        failed = False
        for i in indices:
            item = inputs[i]
            if failed:
                output[i] = RockerSample(item.travel_mm, None, 'not evaluated after branch failure')
                continue
            try:
                if item.rod_suspension is None:
                    raise RockerError('no suspension pose')
                pose = solve_rocker(geometry, item.rod_suspension, previous_angle_rad=previous)
                if abs(pose.angle_rad - previous) > max_angle_step_rad:
                    raise RockerError('rocker angle step too large to track branch')
                output[i] = RockerSample(item.travel_mm, pose, None)
                previous = pose.angle_rad
            except RockerError as error:
                output[i] = RockerSample(item.travel_mm, None, str(error))
                failed = True

    # Unequally spaced central difference; never bridge a missing pose.
    for i in range(1, len(output) - 1):
        before, current, after = output[i - 1], output[i], output[i + 1]
        assert before is not None and current is not None and after is not None
        if before.pose is None or current.pose is None or after.pose is None:
            continue
        left_step = current.travel_mm - before.travel_mm
        right_step = after.travel_mm - current.travel_mm
        left = (current.pose.damper_length_mm - before.pose.damper_length_mm) / left_step
        right = (after.pose.damper_length_mm - current.pose.damper_length_mm) / right_step
        ratio = -(left * right_step + right * left_step) / (left_step + right_step)
        if isfinite(ratio):
            output[i] = RockerSample(current.travel_mm, current.pose, None, ratio)
    assert all(sample is not None for sample in output)
    return tuple(sample for sample in output if sample is not None)
