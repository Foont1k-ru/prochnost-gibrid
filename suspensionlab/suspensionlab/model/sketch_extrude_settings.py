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


# (zero-based element index, 0 for through or blind depth, entry side).
HoleOverride = tuple[int, float, str]


def validate_hole_overrides(thickness: float, direction: str, overrides: tuple[HoleOverride, ...],
                            entity_count: int) -> None:
    if len(overrides) > min(entity_count, 300):
        raise ValueError("Слишком много индивидуальных настроек отверстий")
    seen: set[int] = set()
    for item in overrides:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise ValueError("Некорректные настройки отверстий")
        index, depth, side = item
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < entity_count or index in seen:
            raise ValueError("Некорректный или повторный элемент отверстия")
        if isinstance(depth, bool) or not isinstance(depth, (float, int)):
            raise ValueError("Некорректная глубина отверстия")
        validate_hole_depth(thickness, depth)
        hole_entry_side(direction, side)
        seen.add(index)
