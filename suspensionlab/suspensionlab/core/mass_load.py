"""Предварительная оценка вертикальной нагрузки на одну сторону по массе."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .springs import sprung_mass_per_corner

GRAVITY_M_S2 = 9.80665


@dataclass(frozen=True)
class SymmetricMassLoad:
    total_mass_kg: float
    axle_percent: float
    unsprung_corner_kg: float
    corner_total_kg: float
    corner_sprung_kg: float
    tire_reaction_n: float
    sprung_load_n: float


def symmetric_mass_load(total_mass_kg: float, axle_percent: float, unsprung_corner_kg: float) -> SymmetricMassLoad:
    """Статика, равная левая/правая нагрузка на заданной оси, g = 9.80665.

    Масса неподрессоренных частей относится к одной стороне этой оси.
    Реакция шины и нагрузка, поддерживаемая подвеской, не взаимозаменяемы.
    Нет учёта несимметрии, динамики, аэродинамики, наклона и распределения сил.
    """
    if not isfinite(axle_percent) or not 0 < axle_percent < 100:
        raise ValueError("Доля выбранной оси должна быть строго между 0 и 100 процентами")
    fraction = axle_percent / 100.0
    sprung = sprung_mass_per_corner(total_mass_kg, fraction, unsprung_corner_kg)
    corner = total_mass_kg * fraction / 2
    tire_reaction = corner * GRAVITY_M_S2
    load = sprung * GRAVITY_M_S2
    if not all(isfinite(x) and x > 0 for x in (corner, tire_reaction, load)):
        raise ValueError("Результат невозможно представить с доступной точностью")
    return SymmetricMassLoad(total_mass_kg, axle_percent, unsprung_corner_kg, corner, sprung, tire_reaction, load)
