"""Единые параметры выдавливания для CAD-тела и полигонального просмотра."""
from __future__ import annotations

from math import isfinite
from typing import Literal

ExtrusionDirection = Literal["positive", "negative", "symmetric"]


def extrusion_limits(offset: float, depth: float, direction: str = "positive") -> tuple[float, float]:
    if not isfinite(depth) or not 0 < depth <= 1_000_000:
        raise ValueError("Толщина должна быть больше нуля и не более 1 000 000 мм")
    if not isfinite(offset):
        raise ValueError("Некорректное смещение плоскости")
    if direction == "positive":
        return offset, offset + depth
    if direction == "negative":
        return offset - depth, offset
    if direction == "symmetric":
        return offset - depth / 2, offset + depth / 2
    raise ValueError("Некорректное направление выдавливания")
