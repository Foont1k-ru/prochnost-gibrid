"""Независимый рычаг с центральным корпусом, без проекта и расчётного снимка.

Здесь проверяются параметры и предварительные осевые линии, не CAD-стыковка,
монтаж, кинематика, сварка или прочность. Сохранение и CAD проверяются отдельно.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ball_housing import BallHousingError, ball_housing_centerlines, validate_ball_housing
from .bent_tube import Point3
from .free_arm import FreeArmDraft


class FreeArmHousingError(ValueError):
    """Недопустимый независимый корпус или осевые линии."""


@dataclass(frozen=True, slots=True)
class FreeArmBallHousing:
    outer_diameter_mm: float
    bore_diameter_mm: float
    length_mm: float
    axis: Point3
    offset_mm: Point3

    def __post_init__(self) -> None:
        if not isinstance(self.axis, (tuple, list)) or not isinstance(self.offset_mm, (tuple, list)):
            raise FreeArmHousingError('Ось и смещение задаются тремя координатами')
        try:
            data = validate_ball_housing({'outer_diameter_mm': self.outer_diameter_mm,
                                          'bore_diameter_mm': self.bore_diameter_mm,
                                          'length_mm': self.length_mm, 'axis': list(self.axis),
                                          'offset_mm': list(self.offset_mm)})
        except BallHousingError as error:
            raise FreeArmHousingError(str(error)) from error
        for key in ('outer_diameter_mm', 'bore_diameter_mm', 'length_mm'):
            object.__setattr__(self, key, data[key])
        object.__setattr__(self, 'axis', tuple(data['axis']))
        object.__setattr__(self, 'offset_mm', tuple(data['offset_mm']))

    def as_data(self) -> dict[str, Any]:
        return {'outer_diameter_mm': self.outer_diameter_mm, 'bore_diameter_mm': self.bore_diameter_mm,
                'length_mm': self.length_mm, 'axis': list(self.axis), 'offset_mm': list(self.offset_mm)}

    @classmethod
    def from_data(cls, value: Any) -> FreeArmBallHousing:
        try:
            data = validate_ball_housing(value)
        except BallHousingError as error:
            raise FreeArmHousingError(str(error)) from error
        return cls(data['outer_diameter_mm'], data['bore_diameter_mm'], data['length_mm'],
                   tuple(data['axis']), tuple(data['offset_mm']))


@dataclass(frozen=True, slots=True)
class FreeArmHousingDraft:
    """Неизменяемая пара черновика и корпуса, без подрезки внутренних опор."""

    arm: FreeArmDraft
    housing: FreeArmBallHousing

    def __post_init__(self) -> None:
        if not isinstance(self.arm, FreeArmDraft) or not isinstance(self.housing, FreeArmBallHousing):
            raise FreeArmHousingError('Нужны независимый рычаг и параметры корпуса')
        self.centerlines()  # Validate the shifted center and both bent axes.

    def centerlines(self) -> tuple[tuple[Point3, ...], ...]:
        bends = {leg: {'vertex_mm': bend.vertex_mm, 'radius_mm': bend.radius_mm}
                 for leg, bend in (('front', self.arm.front_bend), ('rear', self.arm.rear_bend))
                 if bend is not None}
        try:
            return ball_housing_centerlines(self.arm.anchors, bends, self.arm.radius_mm, self.housing.as_data())
        except (BallHousingError, ValueError) as error:
            raise FreeArmHousingError(str(error)) from error
