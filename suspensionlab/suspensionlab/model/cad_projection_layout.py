"""Размещение ортографических CAD-видов и справочных габаритов на экране.

Размеры берутся из общих границ тела, а не из видимых ломаных проекции.
Здесь нет CAD-вычислений и нет данных производственного чертежа.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

AXES = {'XY': (0, 1), 'XZ': (0, 2), 'YZ': (1, 2)}
Bounds = tuple[float, float, float, float, float, float]


@dataclass(frozen=True, slots=True)
class ProjectionLayout:
    plane: str
    u_min: float
    u_max: float
    v_min: float
    v_max: float
    scale: float
    center_x: float
    center_y: float

    def screen(self, u: float, v: float) -> tuple[float, float]:
        return (self.center_x + (u - (self.u_min + self.u_max) / 2) * self.scale,
                self.center_y - (v - (self.v_min + self.v_max) / 2) * self.scale)

    @property
    def width_mm(self) -> float:
        return self.u_max - self.u_min

    @property
    def height_mm(self) -> float:
        return self.v_max - self.v_min


def projection_layout(bounds: Bounds, plane: str, width: float, height: float) -> ProjectionLayout:
    """Вписывает общие CAD-границы, сохраняя положительные направления осей.

    Поле слева и снизу отведено под размерные линии; независимый масштаб на
    каждом виде обозначен в интерфейсе. Координаты возвращаются относительно
    левого верхнего угла одного вида, а не всего полотна.
    """
    if (plane not in AXES or len(bounds) != 6 or not all(math.isfinite(x) for x in bounds) or
            any(bounds[i] >= bounds[i + 3] for i in range(3)) or
            not math.isfinite(width) or not math.isfinite(height) or width < 80 or height < 100):
        raise ValueError('invalid projection bounds or viewport')
    u, v = AXES[plane]
    u_min, u_max, v_min, v_max = bounds[u], bounds[u + 3], bounds[v], bounds[v + 3]
    # Header 28px, right padding 10px, annotation margin 42px left / 45px below.
    left, top, right, bottom = 42., 28., width - 10., height - 45.
    scale = min((right - left) / (u_max - u_min), (bottom - top) / (v_max - v_min))
    return ProjectionLayout(plane, u_min, u_max, v_min, v_max, scale,
                            (left + right) / 2, (top + bottom) / 2)


def format_reference_length(value: float) -> str:
    """Текст размера с округлением 0,1 мм без ложного нулевого размера."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError('invalid reference length')
    return '<0.1' if value < 0.05 else f'{value:.1f}'
