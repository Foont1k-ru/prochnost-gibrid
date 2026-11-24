"""Подготовка независимых корпусов внутренних опор без расчётного снимка.

Проверяются только параметры и привязка к явно заданным опорам. CAD-контакт,
монтаж, зазоры конструкции, сварка и прочность здесь не подтверждаются.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bent_tube import Point3
from .fixed_arm_housings import HousingError, validate_housings, validate_notches
from .free_arm import FreeArmDraft
from .free_arm_housing import FreeArmBallHousing, FreeArmHousingDraft


@dataclass(frozen=True, slots=True)
class FreeArmInnerHousing:
    """Конечный полый цилиндр; центр явно подтверждён на внутренней опоре."""

    outer_diameter_mm: float
    bore_diameter_mm: float
    length_mm: float
    axis: Point3
    center_on_pivot: bool

    def __post_init__(self) -> None:
        if not isinstance(self.axis, (tuple, list)):
            raise HousingError('Ось задаётся тремя координатами')
        item = {'outer_diameter_mm': self.outer_diameter_mm, 'bore_diameter_mm': self.bore_diameter_mm,
                'length_mm': self.length_mm, 'axis': list(self.axis), 'center_on_pivot': self.center_on_pivot}
        data = validate_housings({'front': item, 'rear': item})['front']
        for key in ('outer_diameter_mm', 'bore_diameter_mm', 'length_mm'):
            object.__setattr__(self, key, data[key])
        object.__setattr__(self, 'axis', tuple(data['axis']))
        object.__setattr__(self, 'center_on_pivot', True)

    def as_data(self) -> dict[str, Any]:
        return {'outer_diameter_mm': self.outer_diameter_mm, 'bore_diameter_mm': self.bore_diameter_mm,
                'length_mm': self.length_mm, 'axis': list(self.axis), 'center_on_pivot': True}

    @classmethod
    def from_data(cls, value: Any) -> FreeArmInnerHousing:
        data = validate_housings({'front': value, 'rear': value})['front']
        return cls(data['outer_diameter_mm'], data['bore_diameter_mm'], data['length_mm'],
                   tuple(data['axis']), data['center_on_pivot'])


@dataclass(frozen=True, slots=True)
class FreeArmInnerHousings:
    """Два корпуса и независимо выбранные радиальные зазоры подрезки."""

    front: FreeArmInnerHousing
    rear: FreeArmInnerHousing
    front_clearance_mm: float | None = None
    rear_clearance_mm: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.front, FreeArmInnerHousing) or not isinstance(self.rear, FreeArmInnerHousing):
            raise HousingError('Нужны два явно заданных корпуса')
        clearances = {leg: value for leg, value in (('front', self.front_clearance_mm),
                                                    ('rear', self.rear_clearance_mm)) if value is not None}
        if clearances:
            for leg, value in validate_notches(clearances).items():
                object.__setattr__(self, f'{leg}_clearance_mm', value)

    def as_housings(self) -> dict[str, Any]:
        return {'front': self.front.as_data(), 'rear': self.rear.as_data()}

    def as_notches(self) -> dict[str, float] | None:
        result = {leg: value for leg, value in (('front', self.front_clearance_mm),
                                                 ('rear', self.rear_clearance_mm)) if value is not None}
        return result or None

    @classmethod
    def from_data(cls, housings: Any, notches: Any = None) -> FreeArmInnerHousings:
        values = validate_housings(housings)
        cuts = validate_notches(notches) if notches is not None else {}
        return cls(FreeArmInnerHousing.from_data(values['front']), FreeArmInnerHousing.from_data(values['rear']),
                   cuts.get('front'), cuts.get('rear'))


@dataclass(frozen=True, slots=True)
class FreeArmInnerHousingDraft:
    """Независимые точки и два корпуса; центральный корпус опционален."""

    arm: FreeArmDraft
    housings: FreeArmInnerHousings
    ball_housing: FreeArmBallHousing | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.arm, FreeArmDraft) or not isinstance(self.housings, FreeArmInnerHousings):
            raise HousingError('Нужны независимый рычаг и параметры двух корпусов')
        if self.ball_housing is not None:
            if not isinstance(self.ball_housing, FreeArmBallHousing):
                raise HousingError('Недопустимый центральный корпус')
            FreeArmHousingDraft(self.arm, self.ball_housing)
