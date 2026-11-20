"""Явные допущения и пределы проверки расстояний между осями креплений."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

ATTACHMENTS = ('body', 'upright', 'lower_arm')
TYPES = ('double_wishbone', 'multilink_rear')


@dataclass(frozen=True, slots=True)
class ElementSetup:
    """Незаданные поля — None, не выводятся из характеристик пружины/амортизатора."""
    lower: str | None = None
    upper: str | None = None
    minimum_mm: float | None = None
    maximum_mm: float | None = None

    def __post_init__(self) -> None:
        for attachment in (self.lower, self.upper):
            if attachment is not None and attachment not in ATTACHMENTS:
                raise ValueError('Неизвестное крепление')
        for value in (self.minimum_mm, self.maximum_mm):
            if value is not None and (type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 1_000_000):
                raise ValueError('Предел должен быть конечным и положительным')

    def to_dict(self) -> dict[str, Any]:
        return {'lower': self.lower, 'upper': self.upper,
                'minimum_mm': self.minimum_mm, 'maximum_mm': self.maximum_mm}

    @classmethod
    def from_dict(cls, value: Any) -> ElementSetup:
        if not isinstance(value, dict) or set(value) != {'lower', 'upper', 'minimum_mm', 'maximum_mm'}:
            raise ValueError('Некорректная конфигурация элемента')
        return cls(value['lower'], value['upper'], value['minimum_mm'], value['maximum_mm'])


@dataclass(frozen=True, slots=True)
class KinematicElements:
    """Привязаны к типу схемы, чтобы смена типа не переносила допущения молча."""
    type_code: str
    spring: ElementSetup = ElementSetup()
    damper: ElementSetup = ElementSetup()

    def __post_init__(self) -> None:
        if self.type_code not in TYPES or not isinstance(self.spring, ElementSetup) or not isinstance(self.damper, ElementSetup):
            raise ValueError('Некорректная конфигурация проверки')
        if self.type_code == 'multilink_rear' and any(
            mount == 'lower_arm' for element in (self.spring, self.damper) for mount in (element.lower, element.upper)
        ):
            raise ValueError('Крепление на нижнем рычаге неприменимо к пятирычажной схеме')

    def to_dict(self) -> dict[str, Any]:
        return {'type': self.type_code, 'spring': self.spring.to_dict(), 'damper': self.damper.to_dict()}

    @classmethod
    def from_dict(cls, value: Any) -> KinematicElements:
        if not isinstance(value, dict) or set(value) != {'type', 'spring', 'damper'}:
            raise ValueError('Некорректная конфигурация проверки')
        return cls(value['type'], ElementSetup.from_dict(value['spring']), ElementSetup.from_dict(value['damper']))
