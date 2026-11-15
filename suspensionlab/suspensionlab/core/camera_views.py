"""Заранее заданные направления ортографической камеры в системе XYZ."""
from __future__ import annotations

from math import pi
from types import MappingProxyType

# Камера находится со стороны указанной оси и смотрит к центру. Начальная
# ориентация — привычный общий ракурс, не математическая изометрия.
CAMERA_VIEWS = MappingProxyType({
    "default": (-0.65, 0.35),
    "front": (pi / 2, 0.),   # +X
    "rear": (-pi / 2, 0.),    # -X
    "left": (pi, 0.),         # +Y
    "right": (0., 0.),        # -Y
    "top": (0., pi / 2),      # +Z; экран вправо +X, вверх +Y
    "bottom": (0., -pi / 2),  # -Z; экран вправо +X, вверх -Y
})


def camera_view_angles(name: str) -> tuple[float, float]:
    """Только ориентация; система координат и масштаб модели не изменяются."""
    try:
        return CAMERA_VIEWS[name]
    except KeyError as error:
        raise ValueError("Неизвестное направление камеры") from error
