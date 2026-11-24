"""Явные минимумы расстояния пар CAD-деталей фиксированного рычага."""
from __future__ import annotations

import math
from itertools import combinations
from typing import Any

DISTANCE_TOLERANCE_MM = 1e-5
PARTS = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
PAIRS = tuple(f'{a}|{b}' for a, b in combinations(PARTS, 2))
TUBE_PAIR = PAIRS[0]


def validate_requirements(value: Any, *, housings: bool) -> dict[str, float]:
    """Пустой словарь означает отсутствие требований; значений по умолчанию нет."""
    if not isinstance(value, dict) or any(key not in PAIRS for key in value):
        raise ValueError('Неизвестная пара деталей')
    if not housings and any(key != TUBE_PAIR for key in value):
        raise ValueError('Для требований к корпусам должны быть заданы оба корпуса')
    result = {}
    for key, number in value.items():
        if type(number) not in (int, float):
            raise ValueError('Минимум должен быть числом')
        try:
            minimum = float(number)
        except OverflowError as error:
            raise ValueError('Минимум вне диапазона') from error
        if not math.isfinite(minimum) or not (minimum == 0 or DISTANCE_TOLERANCE_MM < minimum <= 100):
            raise ValueError('Укажите 0 или минимум больше 0,00001 и не более 100 мм')
        result[key] = minimum
    return result
