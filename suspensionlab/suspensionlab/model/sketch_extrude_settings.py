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


def validate_hole_depth(thickness: float, hole_depth: float, *, has_holes: bool | None = None) -> None:
    """0 означает сквозные отверстия, иначе глубина строго меньше толщины."""
    if not isfinite(hole_depth) or hole_depth < 0 or hole_depth >= thickness:
        raise ValueError("Глубина глухих отверстий должна быть больше нуля и меньше толщины; 0 означает сквозные")
    if hole_depth > 0 and has_holes is False:
        raise ValueError("Для глухих отверстий нужны внутренние замкнутые контуры")


def hole_entry_side(direction: str, side: str = "auto") -> str:
    """Сторона входа — меньшая или большая координата нормальной оси."""
    if direction not in ("positive", "negative", "symmetric"):
        raise ValueError("Некорректное направление выдавливания")
    if side == "auto":
        return "positive" if direction == "negative" else "negative"
    if side in ("negative", "positive"):
        return side
    raise ValueError("Некорректная сторона входа глухих отверстий")
