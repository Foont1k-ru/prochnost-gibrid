"""Неполный передний рычаг: две трубы по точкам схемы, без креплений."""
from __future__ import annotations

import json
from typing import Any

from .bent_tube import BentTubeError, make_bend_path
from .entities import Project
from .kim_format import KimFormatError, _keys, _name, _number, _scheme
from .niva_arm_views import FRONT, make_niva_arm_view
from .project_io import project_to_json

VERSION = '0.5'
LEGS = ('front', 'rear')


def validate_front_tube_arm(data: Any) -> None:
    doc = _keys(data, {'format', 'version', 'name', 'units', 'frame', 'scheme', 'arm',
                       'radius_mm', 'wall_mm', 'bends'})
    if (doc['format'] != 'kima-assembly' or doc['version'] != VERSION or doc['units'] != 'mm' or
            doc['frame'] != 'front_axle_snapshot' or not isinstance(doc['arm'], str) or doc['arm'] not in FRONT):
        raise KimFormatError('unsupported front arm snapshot')
    _name(doc['name'])
    if doc['scheme'] is None:
        raise KimFormatError('front arm requires scheme snapshot')
    _scheme(doc['scheme'])
    radius, wall = _number(doc['radius_mm'], positive=True), _number(doc['wall_mm'], positive=True)
    if radius < 0.01 or wall < 0.01 or radius - wall < 0.01:
        raise KimFormatError('invalid tube section')
    try:
        view = make_niva_arm_view(Project.from_dict(doc['scheme']), doc['arm'])
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise KimFormatError('invalid front arm source') from error
    bends = doc['bends']
    if not isinstance(bends, dict) or any(key not in LEGS for key in bends):
        raise KimFormatError('invalid bend selection')
    for leg, bend in bends.items():
        bend = _keys(bend, {'vertex_mm', 'radius_mm'})
        if not isinstance(bend['vertex_mm'], list):
            raise KimFormatError('bend vertex must be a list')
        try:
            make_bend_path(view.points[LEGS.index(leg)], bend['vertex_mm'], view.points[2],
                           bend['radius_mm'], radius)
        except BentTubeError as error:
            raise KimFormatError('invalid front tube bend') from error


def make_front_tube_arm(project: Project, arm: str, radius_mm: float, wall_mm: float,
                        bends: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Новый независимый снимок схемы и двух труб, не полный рычаг."""
    try:
        scheme = json.loads(project_to_json(project))
        copied = json.loads(json.dumps({} if bends is None else bends, allow_nan=False))
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise KimFormatError('cannot capture project') from error
    result: dict[str, Any] = {'format': 'kima-assembly', 'version': VERSION,
                              'name': 'Передний рычаг — незавершённый черновик труб', 'units': 'mm',
                              'frame': 'front_axle_snapshot', 'scheme': scheme, 'arm': arm,
                              'radius_mm': radius_mm, 'wall_mm': wall_mm, 'bends': copied}
    validate_front_tube_arm(result)
    return result


def front_tube_arm_points(document: dict[str, Any]) -> tuple[tuple[float, float, float], ...]:
    validate_front_tube_arm(document)
    return make_niva_arm_view(Project.from_dict(document['scheme']), document['arm']).points


def front_tube_arm_centerlines(document: dict[str, Any]) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    points = front_tube_arm_points(document)
    paths = []
    for index, leg in enumerate(LEGS):
        bend = document['bends'].get(leg)
        paths.append((points[index], points[2]) if bend is None else
                     make_bend_path(points[index], bend['vertex_mm'], points[2], bend['radius_mm'],
                                    document['radius_mm']).sample())
    return tuple(paths)
