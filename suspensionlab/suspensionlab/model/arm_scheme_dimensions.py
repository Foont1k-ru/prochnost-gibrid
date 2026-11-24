"""Размеры трёх точек рычага на плане XY, не геометрия труб и не расчёт прочности."""
from __future__ import annotations

import math
from typing import Literal

from .entities import Axle

Arm = Literal['lower', 'upper']
Dimension = Literal['span_x', 'ball_x', 'ball_y', 'position_x']


def arm_codes(axle: Axle, arm: Arm) -> tuple[str, str, str]:
    if axle.role != 'front' or axle.type_code != 'double_wishbone' or arm not in ('lower', 'upper'):
        raise ValueError('Поддерживается передняя двухрычажная подвеска')
    codes = ('lca_f_in', 'lca_r_in', 'lbj') if arm == 'lower' else ('uca_f_in', 'uca_r_in', 'ubj')
    if any(code not in axle.hardpoints for code in codes):
        raise ValueError('Отсутствуют точки рычага')
    return codes


def arm_dimensions(axle: Axle, arm: Arm, *, reference_x: float = 0.) -> dict[Dimension, float]:
    if not math.isfinite(reference_x):
        raise ValueError('Координата исходной точки недопустима')
    front, rear, ball = (axle.hardpoints[code] for code in arm_codes(axle, arm))
    return {'span_x': abs(rear.x - front.x), 'ball_x': abs(ball.x - front.x),
            'ball_y': abs(ball.y - front.y), 'position_x': front.x - reference_x}


def dimension_edits(axle: Axle, arm: Arm, dimension: Dimension, value: float, *,
                    reference_x: float = 0.) -> dict[tuple[str, str], tuple[float, ...]]:
    """Изменить один проекционный размер; не угадывать направление при нуле.

    X положения измеряется от явно выбранной точки, а не от лонжерона.
    Шаровая общая с кулаком; изменение её координаты влияет на связанные элементы.
    """
    limit = 2_000_000_000
    if isinstance(value, bool) or not math.isfinite(value) or not math.isfinite(reference_x) or abs(value) > limit:
        raise ValueError('Размер вне допустимого диапазона')
    codes = arm_codes(axle, arm)
    points = [axle.hardpoints[code].as_tuple() for code in codes]
    if dimension == 'position_x':
        delta = reference_x + value - points[0][0]
        return {(axle.role, code): (p[0] + delta, p[1], p[2]) for code, p in zip(codes, points, strict=True)}
    if dimension not in ('span_x', 'ball_x', 'ball_y') or value < 0:
        raise ValueError('Расстояние должно быть неотрицательным')
    index = 1 if dimension == 'span_x' else 2
    axis = 1 if dimension == 'ball_y' else 0
    difference = points[index][axis] - points[0][axis]
    if abs(difference) < 1e-9 and value > 0:
        raise ValueError('Направление не определено: сначала сместите точку по этой оси')
    direction = -1.0 if difference < 0 else 1.0
    result = list(points[index])
    result[axis] = points[0][axis] + direction * value
    return {(axle.role, codes[index]): tuple(result)}
