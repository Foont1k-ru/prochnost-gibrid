"""Два трубчатых рычага и условные узлы в точках схемы; не готовая сборка."""
from __future__ import annotations

import copy
from typing import Any

from .front_pair_snapshot import validate_front_pair_snapshot
from .joint_concept import validate_joint_concept
from .kim_format import KimFormatError, _keys

VERSION = '0.9'
ALGORITHM = 'front-joint-layout-v1'


def validate_front_joint_layout(value: Any) -> None:
    doc = _keys(value, {'format', 'version', 'algorithm', 'pair', 'ball', 'bushing'})
    if doc['format'] != 'kima-assembly' or doc['version'] != VERSION or doc['algorithm'] != ALGORITHM:
        raise KimFormatError('unsupported front joint layout')
    validate_front_pair_snapshot(doc['pair'])
    for kind in ('ball', 'bushing'):
        validate_joint_concept(doc[kind])
        if doc[kind]['joint_type'] != kind:
            raise KimFormatError('joint type does not match attachment')


def make_front_joint_layout(pair: dict[str, Any], ball: dict[str, Any], bushing: dict[str, Any]) -> dict[str, Any]:
    doc = {'format': 'kima-assembly', 'version': VERSION, 'algorithm': ALGORITHM,
           'pair': copy.deepcopy(pair), 'ball': copy.deepcopy(ball), 'bushing': copy.deepcopy(bushing)}
    validate_front_joint_layout(doc)
    return doc
