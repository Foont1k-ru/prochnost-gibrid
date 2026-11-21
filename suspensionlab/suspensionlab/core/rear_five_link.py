"""Экспериментальная пространственная модель задней пятирычажной стороны.

Пять сферических связей постоянной длины соединяют неподвижный кузов с
жёстким кулаком; ход задаётся вертикальным перемещением центра колеса.
Это не модель сайлентблоков, деформации, упоров или управляемости автомобиля.
"""
from __future__ import annotations

import numpy as np

from ..model.entities import Axle
from .double_wishbone import KinematicsError, RigidFiveLinkSolver

# Ровно пять проектных связей. Их порядок также используется при построении сцены.
LINKS = (('upper_front', 'uf_in', 'uf_out'), ('upper_rear', 'ur_in', 'ur_out'),
         ('lower_front', 'lf_in', 'lf_out'), ('lower_rear', 'lr_in', 'lr_out'),
         ('toe_link', 'toe_in', 'toe_out'))


class RearFiveLink(RigidFiveLinkSolver):
    """Изолированная левая или зеркальная правая сторона независимой задней оси."""

    def __init__(self, axle: Axle, side: str = 'left') -> None:
        if axle.role != 'rear' or axle.type_code != 'multilink_rear':
            raise ValueError('Требуется задняя пятирычажная подвеска')
        if side not in ('left', 'right'):
            raise ValueError('Сторона должна быть left или right')
        self.side = side
        self.sign = 1.0 if side == 'left' else -1.0
        keys = ('wheel_center', *(p for _, a, b in LINKS for p in (a, b)))
        try:
            self.points = {code: np.array((axle.hardpoints[code].x, self.sign * axle.hardpoints[code].y,
                                           axle.hardpoints[code].z), dtype=float) for code in keys}
        except KeyError as error:
            raise KinematicsError(0, f'отсутствует точка {error.args[0]}') from error
        if not all(np.all(np.isfinite(point)) for point in self.points.values()):
            raise KinematicsError(0, 'координаты должны быть конечными числами')
        self.center0 = self.points['wheel_center'].copy()
        self._pairs = tuple((outer, inner) for _, inner, outer in LINKS)
        self._local = np.stack([self.points[outer] - self.center0 for outer, _ in self._pairs])
        self._fixed = np.stack([self.points[inner] for _, inner in self._pairs])
        self._lengths = np.linalg.norm(self._local + self.center0 - self._fixed, axis=1)
        if not np.all(np.isfinite(self._lengths)) or np.any(self._lengths < 1e-6):
            raise KinematicsError(0, 'совпадают шарниры связи или длина некорректна')
        _, jac = self._system(self.center0, np.eye(3), 0.0)
        self._condition(jac, 0.0)
