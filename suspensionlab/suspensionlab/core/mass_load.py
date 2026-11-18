"""Предварительная оценка вертикальной нагрузки на одну сторону по массе."""
from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite
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


CornerKey = Literal["front_left", "front_right", "rear_left", "rear_right"]


@dataclass(frozen=True)
class FourWheelMassLoad:
    """Четыре явно введённых значения одного состояния автомобиля, кг-эквивалент."""

    source_kind: Literal["weighed", "assumed"]
    selected: CornerKey
    front_left_kg: float
    front_right_kg: float
    rear_left_kg: float
    rear_right_kg: float
    total_kg: float
    front_kg: float
    rear_kg: float
    left_kg: float
    right_kg: float
    front_percent: float
    rear_percent: float
    corner_total_kg: float
    unsprung_corner_kg: float
    corner_sprung_kg: float
    tire_reaction_n: float
    sprung_load_n: float

    @property
    def left_percent(self) -> float:
        return self.left_kg / self.total_kg * 100.0

    @property
    def right_percent(self) -> float:
        return self.right_kg / self.total_kg * 100.0

    @property
    def front_left_rear_right_kg(self) -> float:
        return fsum((self.front_left_kg, self.rear_right_kg))

    @property
    def front_right_rear_left_kg(self) -> float:
        return fsum((self.front_right_kg, self.rear_left_kg))

    @property
    def front_left_rear_right_percent(self) -> float:
        return self.front_left_rear_right_kg / self.total_kg * 100.0

    @property
    def front_right_rear_left_percent(self) -> float:
        return self.front_right_rear_left_kg / self.total_kg * 100.0


def four_wheel_mass_load(
    front_left: float, front_right: float, rear_left: float, rear_right: float,
    selected: CornerKey, unsprung_corner_kg: float, source_kind: Literal["weighed", "assumed"],
) -> FourWheelMassLoad:
    """Суммирование четырёх значений и оценка только выбранной стороны.

    Для реальных весов значения должны относиться к одному состоянию и
    горизонтальным площадкам одинаковой высоты. Достоверность данных не проверяется.
    """
    readings = (front_left, front_right, rear_left, rear_right)
    if not all(isfinite(x) and x > 0 for x in readings):
        raise ValueError("Каждое значение под колесом должно быть положительным и конечным")
    keys: tuple[CornerKey, ...] = ("front_left", "front_right", "rear_left", "rear_right")
    if selected not in keys:
        raise ValueError("Не выбрано колесо")
    corner = corner_mass_load(readings[keys.index(selected)], unsprung_corner_kg, source_kind)
    try:
        front, rear = fsum(readings[:2]), fsum(readings[2:])
        left, right = fsum(readings[::2]), fsum(readings[1::2])
        total = fsum(readings)
    except OverflowError as exc:
        raise ValueError("Сумма значений не является конечной") from exc
    if not all(isfinite(x) and x > 0 for x in (front, rear, left, right, total)):
        raise ValueError("Сумма значений не является конечной")
    front_pct, rear_pct = front / total * 100.0, rear / total * 100.0
    if not all(isfinite(x) and x > 0 for x in (front_pct, rear_pct)):
        raise ValueError("Доля оси не представима с доступной точностью")
    return FourWheelMassLoad(
        source_kind, selected, *readings, total, front, rear, left, right, front_pct, rear_pct,
        corner.corner_total_kg, corner.unsprung_corner_kg, corner.corner_sprung_kg,
        corner.tire_reaction_n, corner.sprung_load_n,
    )


MassLoadEstimate = SymmetricMassLoad | CornerMassLoad | FourWheelMassLoad
