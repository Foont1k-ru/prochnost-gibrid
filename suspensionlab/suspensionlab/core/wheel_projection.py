"""Габарит условного неповернутого колеса в ортографических видах."""
from __future__ import annotations


def wheel_projection(mode: str, radius_mm: float, width_mm: float) -> tuple[str, float, float]:
    """Возвращает форму, полуширину и полувысоту в миллиметрах.

    Спереди — прямоугольный профиль шины, сбоку — окружность, сверху —
    прямоугольник. Статические углы и перспективное искажение не моделируются.
    """
    if mode == "front":
        return "rectangle", width_mm / 2, radius_mm
    if mode == "side":
        return "ellipse", radius_mm, radius_mm
    if mode == "top":
        return "rectangle", radius_mm, width_mm / 2
    raise ValueError("Неизвестный вид колеса")
