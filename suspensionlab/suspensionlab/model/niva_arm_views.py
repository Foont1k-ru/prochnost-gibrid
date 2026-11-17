"""Условные отдельные рычаги компоновки Нивы по текущим точкам проекта.

Это не детали из STEP: точки разных осей остаются в своих системах координат.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .bent_tube import MAX_COORDINATE, MIN_SEGMENT
from .entities import Project

Point = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class ArmView:
    key: str
    points: tuple[Point, ...]
    point_codes: tuple[str, ...]
    joint_kinds: tuple[str, ...]

    @property
    def segments(self) -> tuple[tuple[Point, Point], ...]:
        return tuple((point, self.points[-1]) for point in self.points[:-1])


# Front points are left-hand and mirrored by the project convention. Rear
# live-axle points explicitly contain separate left and right coordinates.
FRONT = {
    'front_upper_left': ('uca_f_in', 'uca_r_in', 'ubj'),
    'front_upper_right': ('uca_f_in', 'uca_r_in', 'ubj'),
    'front_lower_left': ('lca_f_in', 'lca_r_in', 'lbj'),
    'front_lower_right': ('lca_f_in', 'lca_r_in', 'lbj'),
}
REAR = {
    'rear_upper_left': ('ul_in_l', 'ul_out_l'),
    'rear_upper_right': ('ul_in_r', 'ul_out_r'),
    'rear_lower_left': ('ll_in_l', 'll_out_l'),
    'rear_lower_right': ('ll_in_r', 'll_out_r'),
    'panhard': ('panhard_body', 'panhard_axle'),
}
ARM_KEYS = (*FRONT, *REAR)


def make_niva_arm_view(project: Project, key: str) -> ArmView:
    """Построить схему по точкам, не меняя проект и не угадывая размеры узлов."""
    codes: tuple[str, ...]
    joints: tuple[str, ...]
    if key in FRONT:
        if project.front.type_code != 'double_wishbone':
            raise ValueError('front_type')
        axle, codes = project.front, FRONT[key]
        mirror = key.endswith('_right')
        joints = ('bushing', 'bushing', 'ball')
    elif key in REAR:
        if project.rear.type_code != 'live_axle_coil' or project.rear.layout != '4link_panhard':
            raise ValueError('rear_type')
        axle, codes = project.rear, REAR[key]
        mirror = False
        joints = ('bushing', 'bushing')
    else:
        raise ValueError('arm')
    points = []
    for code in codes:
        if code not in axle.hardpoints:
            raise ValueError('missing_point')
        point = axle.hardpoints[code]
        coords = point.as_tuple()
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) or abs(v) > MAX_COORDINATE for v in coords):
            raise ValueError('point')
        points.append((float(coords[0]), -float(coords[1]) if mirror else float(coords[1]), float(coords[2])))
    if any(math.dist(p, points[-1]) < MIN_SEGMENT for p in points[:-1]):
        raise ValueError('coincident')
    if len(points) == 3 and math.dist(points[0], points[1]) < MIN_SEGMENT:
        raise ValueError('coincident')
    return ArmView(key, tuple(points), tuple(codes), joints)
