"""Связанная пара задних труб и условные втулки; не инженерная сборка."""
from __future__ import annotations

import copy
from typing import Any

from .joint_concept import validate_joint_concept
from .kim_format import KimFormatError, _keys
from .rear_pair_snapshot import validate_rear_pair_snapshot

VERSION = '0.10'
ALGORITHM = 'rear-joint-layout-v1'
AXES = ('x', 'y', 'z')


def validate_rear_joint_layout(value: Any) -> None:
    doc = _keys(value, {'format', 'version', 'algorithm', 'pair', 'bushing', 'axis'})
    if (doc['format'] != 'kima-assembly' or doc['version'] != VERSION or doc['algorithm'] != ALGORITHM or
            not isinstance(doc['axis'], str) or doc['axis'] not in AXES):
        raise KimFormatError('unsupported rear joint layout')
    validate_rear_pair_snapshot(doc['pair'])
    validate_joint_concept(doc['bushing'])
    if doc['bushing']['joint_type'] != 'bushing':
        raise KimFormatError('expected bushing')


def make_rear_joint_layout(pair: dict[str, Any], bushing: dict[str, Any], axis: str) -> dict[str, Any]:
    doc = {'format': 'kima-assembly', 'version': VERSION, 'algorithm': ALGORITHM,
           'pair': copy.deepcopy(pair), 'bushing': copy.deepcopy(bushing), 'axis': axis}
    validate_rear_joint_layout(doc)
    return doc
