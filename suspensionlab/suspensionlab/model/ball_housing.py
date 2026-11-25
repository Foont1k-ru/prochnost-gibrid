"""Явная геометрия отдельного корпуса у шаровой; не изделие и не проверка прочности."""
from __future__ import annotations

import math
from typing import Any


class BallHousingError(ValueError):
    """Данные отсутствуют или геометрия корпуса недопустима."""


def validate_ball_housing(value: Any) -> dict[str, Any]:
    keys = {'outer_diameter_mm', 'bore_diameter_mm', 'length_mm', 'axis', 'offset_mm'}
    if not isinstance(value, dict) or set(value) != keys:
        raise BallHousingError('Нужны размеры, направление оси и смещение корпуса')

    def number(item: Any, low: float, high: float) -> float:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise BallHousingError('Требуется конечное число')
        try:
            result = float(item)
        except OverflowError as error:
            raise BallHousingError('Значение вне допустимого диапазона') from error
        if not math.isfinite(result) or not low <= result <= high:
            raise BallHousingError('Значение вне допустимого диапазона')
        return result

    outside = number(value['outer_diameter_mm'], .02, 20_000)
    bore = number(value['bore_diameter_mm'], .01, 20_000)
    length = number(value['length_mm'], .01, 20_000)
    if bore >= outside:
        raise BallHousingError('Отверстие должно быть меньше наружного диаметра')
    vectors = []
    for key in ('axis', 'offset_mm'):
        vector = value[key]
        if not isinstance(vector, list) or len(vector) != 3:
            raise BallHousingError('Нужны три компоненты XYZ')
        vectors.append([number(item, -1_000_000, 1_000_000) for item in vector])
    if math.hypot(*vectors[0]) < 1e-9:
        raise BallHousingError('Ось корпуса не может быть нулевой')
    return {'outer_diameter_mm': outside, 'bore_diameter_mm': bore, 'length_mm': length,
            'axis': vectors[0], 'offset_mm': vectors[1]}


def ball_housing_centerlines(anchors: tuple[tuple[float, float, float], ...],
                             bends: dict[str, dict[str, Any]], radius_mm: float,
                             parameters: dict[str, Any]) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    """Оси до центра корпуса, без представления о фактическом резе и без CAD."""
    from .bent_tube import make_bend_path

    data = validate_ball_housing(parameters)
    if len(anchors) != 3:
        raise BallHousingError('Нужны три опоры рычага')
    center = tuple(anchors[2][i] + data['offset_mm'][i] for i in range(3))
    if any(not math.isfinite(value) or abs(value) > 1_000_000 for value in center):
        raise BallHousingError('Центр корпуса вне допустимого диапазона')
    paths = []
    for index, leg in enumerate(('front', 'rear')):
        if leg in bends:
            bend = bends[leg]
            try:
                path = make_bend_path(anchors[index], bend['vertex_mm'], center, bend['radius_mm'], radius_mm)
            except ValueError as error:
                raise BallHousingError('Изгиб не достигает центра корпуса; измените форму или смещение') from error
            paths.append(path.sample())
        else:
            if math.dist(anchors[index], center) < .01:
                raise BallHousingError('Опора совпала с центром корпуса')
            paths.append((anchors[index], center))
    return tuple(paths)  # type: ignore[return-value]
