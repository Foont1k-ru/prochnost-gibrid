"""Предварительная оценка вертикальной нагрузки на одну сторону по массе."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

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


@dataclass(frozen=True)
class CornerMassLoad:
    """Введённое значение для выбранного колеса; происхождение задано пользователем."""

    source_kind: Literal["weighed", "assumed"]
    corner_total_kg: float
    unsprung_corner_kg: float
    corner_sprung_kg: float
    tire_reaction_n: float
    sprung_load_n: float


MassLoadEstimate = SymmetricMassLoad | CornerMassLoad


def corner_mass_load(corner_kg: float, unsprung_corner_kg: float,
                     source_kind: Literal["weighed", "assumed"]) -> CornerMassLoad:
    """Сила на весах в кг-эквиваленте или предположение, не масса детали.

    Вычет неподрессоренной массы — приблизительное допущение для выбранной
    стороны; сам факт измерения, равномерность высоты площадок и прочие силы
    не проверяются. Результат — не сила пружины и не распределение на четыре колеса.
    """
    if source_kind not in ("weighed", "assumed"):
        raise ValueError("Не указан источник значения для колеса")
    if not isfinite(corner_kg) or corner_kg <= 0 or not isfinite(unsprung_corner_kg) or unsprung_corner_kg < 0:
        raise ValueError("Значение колеса должно быть положительным, неподрессоренная масса — неотрицательной")
    sprung = corner_kg - unsprung_corner_kg
    reaction = corner_kg * GRAVITY_M_S2
    load = sprung * GRAVITY_M_S2
    if not all(isfinite(value) and value > 0 for value in (sprung, reaction, load)):
        raise ValueError("Неподрессоренная масса должна быть меньше показания; результат должен быть конечным")
    return CornerMassLoad(source_kind, corner_kg, unsprung_corner_kg, sprung, reaction, load)
