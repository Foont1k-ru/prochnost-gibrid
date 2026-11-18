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
AXIS_VERSION = '0.13'
AXIS_ALGORITHM = 'front-joint-layout-axis-v2'
SAME_AXIS_VERSION = '0.14'
SAME_AXIS_ALGORITHM = 'front-same-joint-layout-axis-v2'
LAYOUT_VERSIONS = (VERSION, SAME_VERSION, AXIS_VERSION, SAME_AXIS_VERSION)


def validate_front_joint_layout(value: Any) -> None:
    if not isinstance(value, dict):
        raise KimFormatError('unsupported front joint layout')
    modern = value.get('version') in (AXIS_VERSION, SAME_AXIS_VERSION)
    fields = {'format', 'version', 'algorithm', 'pair', 'ball', 'bushing'}
    if modern:
        fields.add('axis')
    doc = _keys(value, fields)
    if doc['format'] != 'kima-assembly':
        raise KimFormatError('unsupported front joint layout')
    if (doc['version'], doc['algorithm']) in ((VERSION, ALGORITHM), (AXIS_VERSION, AXIS_ALGORITHM)):
        validate_front_pair_snapshot(doc['pair'])
    elif (doc['version'], doc['algorithm']) in ((SAME_VERSION, SAME_ALGORITHM), (SAME_AXIS_VERSION, SAME_AXIS_ALGORITHM)):
        validate_front_same_pair(doc['pair'])
    else:
        raise KimFormatError('unsupported front joint layout')
    if modern and doc['axis'] not in ('x', 'y', 'z'):
        raise KimFormatError('unsupported bushing axis')
    for kind in ('ball', 'bushing'):
        validate_joint_concept(doc[kind])
        if doc[kind]['joint_type'] != kind:
            raise KimFormatError('joint type does not match attachment')


def front_bushing_axis(doc: dict[str, Any]) -> str:
    """Старые версии имеют фиксированную ось Y; новые хранят явный выбор."""
    validate_front_joint_layout(doc)
    return str(doc['axis']) if doc['version'] in (AXIS_VERSION, SAME_AXIS_VERSION) else 'y'


def make_front_joint_layout(pair: dict[str, Any], ball: dict[str, Any], bushing: dict[str, Any], *,
                            axis: str | None = None) -> dict[str, Any]:
    same = pair.get('version') == '0.11'
    if axis is None:
        version, algorithm = (SAME_VERSION, SAME_ALGORITHM) if same else (VERSION, ALGORITHM)
    else:
        version, algorithm = (SAME_AXIS_VERSION, SAME_AXIS_ALGORITHM) if same else (AXIS_VERSION, AXIS_ALGORITHM)
    doc = {'format': 'kima-assembly', 'version': version, 'algorithm': algorithm,
           'pair': copy.deepcopy(pair), 'ball': copy.deepcopy(ball), 'bushing': copy.deepcopy(bushing)}
    if axis is not None:
        doc['axis'] = axis
    validate_front_joint_layout(doc)
    return doc
