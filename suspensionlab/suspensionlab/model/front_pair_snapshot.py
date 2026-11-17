"""Связанный снимок зеркальных передних труб, не полноценная CAD-деталь."""
from __future__ import annotations

import copy
from typing import Any

from .front_tube_arm import validate_front_tube_arm
from .kim_format import KimFormatError, _keys

VERSION = '0.7'
ALGORITHM = 'front-mirror-y-v1'
PAIRS = {'front_upper_left': 'front_upper_right', 'front_upper_right': 'front_upper_left',
         'front_lower_left': 'front_lower_right', 'front_lower_right': 'front_lower_left'}


def mirror_front_tube_arm(source: dict[str, Any]) -> dict[str, Any]:
    """Зеркальная геометрия Y текущей передней оси; вход не меняется."""
    validate_front_tube_arm(source)
    result = copy.deepcopy(source)
    result['arm'] = PAIRS[source['arm']]
    for bend in result['bends'].values():
        bend['vertex_mm'][1] = -bend['vertex_mm'][1]
    validate_front_tube_arm(result)
    return result


def validate_front_pair_snapshot(value: Any) -> None:
    doc = _keys(value, {'format', 'version', 'algorithm', 'source'})
    if doc['format'] != 'kima-assembly' or doc['version'] != VERSION or doc['algorithm'] != ALGORITHM:
        raise KimFormatError('unsupported front mirror snapshot')
    mirror_front_tube_arm(doc['source'])


def make_front_pair_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    doc = {'format': 'kima-assembly', 'version': VERSION, 'algorithm': ALGORITHM, 'source': copy.deepcopy(source)}
    validate_front_pair_snapshot(doc)
    return doc


def front_pair_sides(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_front_pair_snapshot(document)
    source = copy.deepcopy(document['source'])
    return source, mirror_front_tube_arm(source)
