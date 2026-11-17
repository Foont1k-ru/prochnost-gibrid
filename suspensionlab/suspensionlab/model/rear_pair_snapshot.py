"""Связанный исследовательский снимок пары задних труб .kima 0.6.

Второй экземпляр вычисляется из одной исходной трубы и сохранённого правила.
Этот файл не является полной сборкой и не задаёт установку шарниров.
"""
from __future__ import annotations

import copy
from typing import Any

from .kim_format import KimFormatError, _keys
from .rear_tube import validate_rear_tube
from .rear_tube_pair import make_paired_rear_tube

VERSION = '0.6'
ALGORITHM = 'rear-pair-v1'


def validate_rear_pair_snapshot(value: Any) -> None:
    doc = _keys(value, {'format', 'version', 'algorithm', 'source', 'mode', 'roll_degrees'})
    if doc['format'] != 'kima-assembly' or doc['version'] != VERSION or doc['algorithm'] != ALGORITHM:
        raise KimFormatError('unsupported rear pair snapshot')
    validate_rear_tube(doc['source'])
    make_paired_rear_tube(doc['source'], doc['mode'], doc['roll_degrees'])


def make_rear_pair_snapshot(source: dict[str, Any], mode: str, roll_degrees: float = 0) -> dict[str, Any]:
    result = {'format': 'kima-assembly', 'version': VERSION, 'algorithm': ALGORITHM,
              'source': copy.deepcopy(source), 'mode': mode, 'roll_degrees': roll_degrees}
    validate_rear_pair_snapshot(result)
    return result


def rear_pair_sides(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_rear_pair_snapshot(document)
    source = copy.deepcopy(document['source'])
    return source, make_paired_rear_tube(source, document['mode'], document['roll_degrees'])
