"""Преобразование одной задней трубы в парную, без модели креплений.

Одинаковая физическая деталь размещается только собственным вращением
(определитель +1), отражённая — отражением Y. Две точки не задают закрутку:
нулевое вращение вокруг оси здесь лишь явная математическая договорённость.
"""
from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

from .entities import Project
from .kim_format import KimFormatError
from .niva_arm_views import make_niva_arm_view
from .rear_tube import rear_tube_points, validate_rear_tube

PAIRS = {
    'rear_upper_left': 'rear_upper_right', 'rear_upper_right': 'rear_upper_left',
    'rear_lower_left': 'rear_lower_right', 'rear_lower_right': 'rear_lower_left',
}
TOLERANCE_MM = 1e-6  # геометрическое совпадение, не производственный допуск


def make_paired_rear_tube(document: dict[str, Any], mode: str, roll_degrees: float = 0) -> dict[str, Any]:
    """Создать снимок парной трубы, не изменяя входной документ или проект.

    Обе стороны берутся из снимка проекта; они не исправляются автоматически.
    Положение дополнительных креплений и возможность реальной установки неизвестны.
    """
    validate_rear_tube(document)
    arm = document['arm']
    if arm not in PAIRS or mode not in ('mirror', 'same'):
        raise KimFormatError('no supported pair or mode')
    if (isinstance(roll_degrees, bool) or not isinstance(roll_degrees, (int, float)) or
            not math.isfinite(roll_degrees) or not -180 <= roll_degrees <= 180):
        raise KimFormatError('invalid roll')
    if mode == 'mirror' and roll_degrees != 0:
        raise KimFormatError('roll not applicable to reflection')
    original = np.array(rear_tube_points(document), dtype=float)
    try:
        target = np.array(make_niva_arm_view(Project.from_dict(document['scheme']), PAIRS[arm]).points, dtype=float)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise KimFormatError('invalid opposite side') from error
    if mode == 'mirror':
        if not np.allclose(original * [1, -1, 1], target, rtol=0, atol=TOLERANCE_MM):
            raise KimFormatError('opposite points are not mirrored')
        def transform(vertex: Any) -> Any:
            return np.asarray(vertex, dtype=float) * [1, -1, 1]
    else:
        v, w = original[1] - original[0], target[1] - target[0]
        lv, lw = np.linalg.norm(v), np.linalg.norm(w)
        if abs(lv - lw) > TOLERANCE_MM:
            raise KimFormatError('opposite points have unequal lengths')
        a, b = v / lv, w / lw
        cross, dot = np.cross(a, b), float(np.clip(np.dot(a, b), -1, 1))
        sine = float(np.linalg.norm(cross))
        if sine > 1e-12:
            axis, angle = cross / sine, math.atan2(sine, dot)
        elif dot < 0:
            basis = np.eye(3)[int(np.argmin(np.abs(a)))]
            axis = np.cross(a, basis)
            axis = axis / np.linalg.norm(axis)
            angle = math.pi
        else:
            axis, angle = b, 0.0
        def rotate(vec: Any, around: Any, radians: float) -> Any:
            return (vec * math.cos(radians) + np.cross(around, vec) * math.sin(radians) +
                    around * np.dot(around, vec) * (1 - math.cos(radians)))
        def transform(vertex: Any) -> Any:
            offset = np.asarray(vertex, dtype=float) - original[0]
            return target[0] + rotate(rotate(offset, axis, angle), b, math.radians(roll_degrees))
    result = copy.deepcopy(document)
    result['arm'] = PAIRS[arm]
    if result['bend'] is not None:
        result['bend']['vertex_mm'] = transform(result['bend']['vertex_mm']).tolist()
    validate_rear_tube(result)
    return result
