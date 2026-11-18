"""Преобразование координат между внутренней ISO и представлением SAE."""
from __future__ import annotations

from .geometry import Vec3


def iso_to_sae(point: Vec3) -> Vec3:
    """Переводит (X вперёд, Y влево, Z вверх) в (X вперёд, Y вправо, Z вниз)."""
    return (point[0], -point[1], -point[2])


def sae_to_iso(point: Vec3) -> Vec3:
    """Обратное преобразование SAE в ISO; начало координат не изменяется."""
    return iso_to_sae(point)
