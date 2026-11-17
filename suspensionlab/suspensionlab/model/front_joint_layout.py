"""Два трубчатых рычага и условные узлы в точках схемы; не готовая сборка."""
from __future__ import annotations

import copy
from typing import Any

from .front_pair_snapshot import validate_front_pair_snapshot
from .front_same_pair import validate_front_same_pair
from .joint_concept import validate_joint_concept
from .kim_format import KimFormatError, _keys

VERSION = '0.9'
ALGORITHM = 'front-joint-layout-v1'
SAME_VERSION = '0.12'
SAME_ALGORITHM = 'front-same-joint-layout-v1'


def validate_front_joint_layout(value: Any) -> None:
    doc = _keys(value, {'format', 'version', 'algorithm', 'pair', 'ball', 'bushing'})
    if doc['format'] != 'kima-assembly':
        raise KimFormatError('unsupported front joint layout')
    if doc['version'] == VERSION and doc['algorithm'] == ALGORITHM:
        validate_front_pair_snapshot(doc['pair'])
    elif doc['version'] == SAME_VERSION and doc['algorithm'] == SAME_ALGORITHM:
        validate_front_same_pair(doc['pair'])
    else:
        raise KimFormatError('unsupported front joint layout')
    for kind in ('ball', 'bushing'):
        validate_joint_concept(doc[kind])
        if doc[kind]['joint_type'] != kind:
            raise KimFormatError('joint type does not match attachment')


def make_front_joint_layout(pair: dict[str, Any], ball: dict[str, Any], bushing: dict[str, Any]) -> dict[str, Any]:
    version, algorithm = ((SAME_VERSION, SAME_ALGORITHM) if pair.get('version') == '0.11'
                          else (VERSION, ALGORITHM))
    doc = {'format': 'kima-assembly', 'version': version, 'algorithm': algorithm,
           'pair': copy.deepcopy(pair), 'ball': copy.deepcopy(ball), 'bushing': copy.deepcopy(bushing)}
    validate_front_joint_layout(doc)
    return doc
