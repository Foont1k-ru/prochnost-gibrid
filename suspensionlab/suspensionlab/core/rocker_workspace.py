"""Экспериментальная связь тяги с дискретной кинематикой одной оси.

Геометрия коромысла задана в координатах левой стороны и неподвижного кузова.
Этот API также используется рабочей областью при явно включённом коромысле.
"""
from __future__ import annotations

from collections.abc import Sequence
from math import ceil, isfinite

import numpy as np

from ..model.entities import Axle
from .double_wishbone import DoubleWishbone
from .kinematics_workspace import supported
from .rear_five_link import RearFiveLink
from .rocker_kinematics import RockerGeometry, RockerInput, RockerSample, solve_rocker_sweep
from .springs import lower_arm_point
from .sweep import limited_sweep, travel_grid


def calculate_rocker(axle: Axle, geometry: RockerGeometry, rod_mount: str,
                     start_mm: float, end_mm: float, *, targets: Sequence[float] | None = None) -> tuple[RockerSample, ...]:
    """Кинематика тяги и амортизатора на сетке не крупнее 2 мм.

    Шарнир тяги жёстко связан с кулаком либо (только спереди) нижним рычагом.
    Ось и второй конец амортизатора закреплены на неподвижном кузове. Поворот
    коромысла определяется из неизменной длины тяги. Отказ подвески или ветви
    коромысла не экстраполируется. Полученные точки и разностное передаточное
    отношение не проверяют промежутки, столкновения, шарниры, силы или прочность.
    """
    if not supported(axle):
        raise ValueError('Расчёт коромысла для этой подвески не реализован')
    if rod_mount not in ('upright', 'lower_arm') or (rod_mount == 'lower_arm' and axle.role != 'front'):
        raise ValueError('Крепление тяги неприменимо к этой схеме')
    if (type(start_mm) not in (int, float) or type(end_mm) not in (int, float) or
            not isfinite(start_mm) or not isfinite(end_mm) or not -150 <= start_mm <= 0 <= end_mm <= 150):
        raise ValueError('Диапазон должен включать ноль и быть в пределах −150…+150 мм')
    if targets is None:
        travels = travel_grid(start_mm, end_mm, max_spacing_mm=2.)
    else:
        if (len(targets) > 5000 or any(type(t) not in (int, float) or not isfinite(t) or
                                       not start_mm <= t <= end_mm for t in targets)):
            raise ValueError('Некорректные точки хода')
        boundaries = sorted({start_mm, 0., end_mm, *targets})
        travels = [boundaries[0]]
        for a, b in zip(boundaries, boundaries[1:], strict=False):
            count = ceil((b - a) / 2.)
            travels.extend(b if i == count else a + (b - a) * i / count for i in range(1, count + 1))
        if len(travels) > 5000:
            raise ValueError('Слишком много точек хода')
    model = DoubleWishbone(axle, 'left') if axle.role == 'front' else RearFiveLink(axle, 'left')
    sweep = limited_sweep(model, travels, max_step_mm=2.)
    original = np.array(geometry.rod_suspension, dtype=float)
    inputs: list[RockerInput] = []
    for row in sweep.points:
        if row.pose is None:
            inputs.append(RockerInput(row.travel_mm, None))
            continue
        try:
            if rod_mount == 'upright':
                point = row.pose.point(original, model.center0)
            elif isinstance(model, DoubleWishbone):
                point = lower_arm_point(model, row.pose, original)
            else:
                raise ValueError('Крепление неприменимо')
            if not np.all(np.isfinite(point)):
                raise ValueError('Неконечные координаты тяги')
            inputs.append(RockerInput(row.travel_mm, (float(point[0]), float(point[1]), float(point[2]))))
        except (ValueError, ArithmeticError):
            # A failed attachment transform is not replaced with a previous point.
            inputs.append(RockerInput(row.travel_mm, None))
    return solve_rocker_sweep(geometry, inputs)
