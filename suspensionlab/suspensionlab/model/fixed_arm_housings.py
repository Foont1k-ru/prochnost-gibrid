"""Явные параметры двух корпусов; не готовая сборка и не KIMA-документ."""
from __future__ import annotations

import json
import math
from typing import Any

from .welded_arm import weldment_source_matches

PREVIEW_FORMAT = 'suspensionlab-fixed-arm-housing-preview'
PREVIEW_VERSION = '1'


class HousingError(ValueError):
    """Параметры корпуса отсутствуют или геометрически недопустимы."""


def _number(value: Any, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HousingError('Введите конечные числовые параметры корпусов')
    try:
        number = float(value)
    except OverflowError as error:
        raise HousingError('Число вне допустимого диапазона') from error
    if not math.isfinite(number) or not low <= number <= high:
        raise HousingError('Число вне допустимого диапазона')
    return number


def validate_housings(value: Any) -> dict[str, Any]:
    """Два независимых корпуса; центры опор подтверждены явно пользователем.

    Ограничения — программные пределы, не инженерные нормы. Ось может быть
    произвольной пространственной; её масштаб не влияет на направление.
    """
    if not isinstance(value, dict) or set(value) != {'front', 'rear'}:
        raise HousingError('Нужны параметры обоих корпусов')
    result: dict[str, Any] = {}
    for leg, label in (('front', 'Передний'), ('rear', 'Задний')):
        item = value[leg]
        if not isinstance(item, dict) or set(item) != {'outer_diameter_mm', 'bore_diameter_mm', 'length_mm',
                                                    'axis', 'center_on_pivot'}:
            raise HousingError(f'{label} корпус: неверный набор параметров')
        if item['center_on_pivot'] is not True:
            raise HousingError(f'{label} корпус: подтвердите совпадение центра с опорой')
        outer = _number(item['outer_diameter_mm'], low=0.02, high=20000)
        bore = _number(item['bore_diameter_mm'], low=0.01, high=20000)
        length = _number(item['length_mm'], low=0.01, high=20000)
        if bore >= outer:
            raise HousingError(f'{label} корпус: диаметр отверстия должен быть меньше наружного')
        axis = item['axis']
        if not isinstance(axis, list) or len(axis) != 3:
            raise HousingError(f'{label} корпус: нужны три компоненты оси')
        vector = [_number(x, low=-1_000_000, high=1_000_000) for x in axis]
        if math.hypot(*vector) < 1e-9:
            raise HousingError(f'{label} корпус: ось не может быть нулевой')
        result[leg] = {'outer_diameter_mm': outer, 'bore_diameter_mm': bore, 'length_mm': length,
                       'axis': vector, 'center_on_pivot': True}
    return result


def validate_housing_preview(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {'format', 'version', 'name', 'tubes', 'housings'}:
        raise HousingError('Неверный временный снимок CAD')
    if (value['format'] != PREVIEW_FORMAT or value['version'] != PREVIEW_VERSION or
            value['name'] != 'Трубы и корпуса — предварительный просмотр'):
        raise HousingError('Неизвестный временный снимок CAD')
    try:
        if not weldment_source_matches(value['tubes']):
            raise HousingError('Опоры труб не совпадают со снимком')
        validate_housings(value['housings'])
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise HousingError('Недопустимый снимок труб или корпусов') from error


def make_housing_preview(tubes: dict[str, Any], housings: dict[str, Any]) -> dict[str, Any]:
    doc = {'format': PREVIEW_FORMAT, 'version': PREVIEW_VERSION,
           'name': 'Трубы и корпуса — предварительный просмотр',
           'tubes': tubes, 'housings': validate_housings(housings)}
    validate_housing_preview(doc)
    return json.loads(json.dumps(doc, ensure_ascii=False, allow_nan=False))
