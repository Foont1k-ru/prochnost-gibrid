"""Параметрический условный шарнир в локальной системе; не готовое изделие."""
from __future__ import annotations

import copy
from typing import Any

from .kim_format import KimFormatError, _keys, _name, _number

VERSION = '0.8'
ALGORITHM = 'joint-concept-z-v1'
DEFAULTS: dict[str, dict[str, float]] = {
    'ball': {'outer_radius_mm': 22, 'cavity_radius_mm': 14, 'ball_radius_mm': 13,
             'opening_radius_mm': 8, 'pin_radius_mm': 5, 'pin_length_mm': 45},
    'bushing': {'outer_radius_mm': 14, 'bore_radius_mm': 7, 'pin_radius_mm': 6,
                'body_length_mm': 24, 'pin_length_mm': 34},
}


def validate_joint_concept(value: Any) -> None:
    doc = _keys(value, {'format', 'version', 'algorithm', 'name', 'units', 'joint_type', 'parameters'})
    if (doc['format'] != 'kima-assembly' or doc['version'] != VERSION or doc['algorithm'] != ALGORITHM or
            doc['units'] != 'mm' or not isinstance(doc['joint_type'], str) or doc['joint_type'] not in DEFAULTS):
        raise KimFormatError('unsupported joint concept')
    _name(doc['name'])
    kind = doc['joint_type']
    raw = _keys(doc['parameters'], set(DEFAULTS[kind]))
    p = {key: _number(value, positive=True) for key, value in raw.items()}
    if any(not .1 <= val <= 500 for val in p.values()):
        raise KimFormatError('joint input outside geometric limits')
    # Numerical geometric guards only; these are NOT manufacturing clearances.
    if kind == 'ball':
        if (p['outer_radius_mm'] - p['cavity_radius_mm'] < 0.5 or
            p['cavity_radius_mm'] - p['ball_radius_mm'] < 0.1 or
            p['ball_radius_mm'] - p['opening_radius_mm'] < 0.5 or
            p['opening_radius_mm'] - p['pin_radius_mm'] < 0.1 or
            p['pin_length_mm'] - p['outer_radius_mm'] < 1):
            raise KimFormatError('invalid conditional ball geometry')
    elif (p['outer_radius_mm'] - p['bore_radius_mm'] < 0.5 or
          p['bore_radius_mm'] - p['pin_radius_mm'] < 0.1 or
          p['pin_length_mm'] - p['body_length_mm'] < 1):
        raise KimFormatError('invalid conditional bushing geometry')


def make_joint_concept(kind: str, parameters: dict[str, float], *, name: str = 'Условный шарнир') -> dict[str, Any]:
    doc = {'format': 'kima-assembly', 'version': VERSION, 'algorithm': ALGORITHM,
           'name': name, 'units': 'mm', 'joint_type': kind, 'parameters': copy.deepcopy(parameters)}
    validate_joint_concept(doc)
    return doc
