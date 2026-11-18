"""Одинаковые передние трубные рычаги: только жёсткое вращение и перенос."""
from __future__ import annotations

import copy
from typing import Any

import numpy as np

from .entities import Project
from .front_pair_snapshot import PAIRS
from .front_tube_arm import front_tube_arm_points, validate_front_tube_arm
from .kim_format import KimFormatError, _keys
from .niva_arm_views import make_niva_arm_view

VERSION = '0.11'
ALGORITHM = 'front-same-three-points-v1'
# Numerical safeguards, not manufacturing tolerances.
TOLERANCE_MM = 1e-6
MIN_RELATIVE_HEIGHT = 1e-8


def same_front_tube_arm(source: dict[str, Any]) -> dict[str, Any]:
    """Align labelled, non-collinear supports using a proper rotation, never a reflection.

    Corresponding attachment directions are not known. Only the experimental
    tube centerlines and bend vertices are transformed; real mounting and the
    orientation of any additional parts must be checked separately.
    """
    validate_front_tube_arm(source)
    points = np.asarray(front_tube_arm_points(source), dtype=float)
    try:
        target = np.asarray(make_niva_arm_view(Project.from_dict(source['scheme']), PAIRS[source['arm']]).points,
                            dtype=float)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise KimFormatError('invalid opposite front points') from error

    def frame(p: Any) -> Any:
        x = p[1] - p[0]
        length = float(np.linalg.norm(x))
        if length < TOLERANCE_MM:
            raise KimFormatError('support points coincide')
        x = x / length
        v = p[2] - p[0]
        y = v - np.dot(v, x) * x
        height = float(np.linalg.norm(y))
        if height < max(TOLERANCE_MM, float(np.linalg.norm(v)) * MIN_RELATIVE_HEIGHT):
            raise KimFormatError('three supports do not define a stable orientation')
        y = y / height
        z = np.cross(x, y)
        return np.column_stack((x, y, z))

    source_frame, target_frame = frame(points), frame(target)
    rotation = target_frame @ source_frame.T
    moved = (rotation @ (points - points[0]).T).T + target[0]
    if not np.allclose(moved, target, rtol=0, atol=TOLERANCE_MM):
        raise KimFormatError('opposite support triangles do not match')
    result = copy.deepcopy(source)
    result['arm'] = PAIRS[source['arm']]
    for bend in result['bends'].values():
        vertex = np.asarray(bend['vertex_mm'], dtype=float)
        bend['vertex_mm'] = (target[0] + rotation @ (vertex - points[0])).tolist()
    validate_front_tube_arm(result)
    return result


def validate_front_same_pair(value: Any) -> None:
    doc = _keys(value, {'format', 'version', 'algorithm', 'source'})
    if doc['format'] != 'kima-assembly' or doc['version'] != VERSION or doc['algorithm'] != ALGORITHM:
        raise KimFormatError('unsupported front same-part pair')
    same_front_tube_arm(doc['source'])


def make_front_same_pair(source: dict[str, Any]) -> dict[str, Any]:
    doc = {'format': 'kima-assembly', 'version': VERSION, 'algorithm': ALGORITHM, 'source': copy.deepcopy(source)}
    validate_front_same_pair(doc)
    return doc


def front_same_pair_sides(doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_front_same_pair(doc)
    source = copy.deepcopy(doc['source'])
    return source, same_front_tube_arm(source)
