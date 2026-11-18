"""Одна незавершённая задняя тяга: снимок схемы и полая труба, без шарниров."""
from __future__ import annotations

import json
from typing import Any

from .bent_tube import BentTubeError, make_bend_path
from .entities import Project
from .kim_format import KimFormatError, _keys, _name, _number, _scheme
from .niva_arm_views import REAR, make_niva_arm_view
from .project_io import project_to_json

VERSION = '0.4'


def validate_rear_tube(data: Any) -> None:
    doc = _keys(data, {'format', 'version', 'name', 'units', 'frame', 'scheme', 'arm',
                       'radius_mm', 'wall_mm', 'bend'})
    if (doc['format'] != 'kima-assembly' or doc['version'] != VERSION or doc['units'] != 'mm' or
            doc['frame'] != 'rear_axle_snapshot' or not isinstance(doc['arm'], str) or doc['arm'] not in REAR):
        raise KimFormatError('unsupported rear tube snapshot')
    _name(doc['name'])
    if doc['scheme'] is None:
        raise KimFormatError('rear tube requires scheme snapshot')
    _scheme(doc['scheme'])
    radius, wall = _number(doc['radius_mm'], positive=True), _number(doc['wall_mm'], positive=True)
    if radius < 0.01 or wall < 0.01 or radius - wall < 0.01:
        raise KimFormatError('invalid tube section')
    try:
        project = Project.from_dict(doc['scheme'])
        view = make_niva_arm_view(project, doc['arm'])
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise KimFormatError('invalid rear tube source') from error
    if doc['bend'] is not None:
        bend = _keys(doc['bend'], {'vertex_mm', 'radius_mm'})
        if not isinstance(bend['vertex_mm'], list):
            raise KimFormatError('bend vertex must be a list')
        try:
            make_bend_path(view.points[0], bend['vertex_mm'], view.points[1], bend['radius_mm'], radius)
        except BentTubeError as error:
            raise KimFormatError('invalid rear tube bend') from error


def make_rear_tube(project: Project, arm: str, radius_mm: float, wall_mm: float,
                   bend: dict[str, Any] | None = None) -> dict[str, Any]:
    """Создаёт независимый снимок текущего проекта; форма креплений не задана."""
    try:
        scheme = json.loads(project_to_json(project))
        bend_copy = None if bend is None else json.loads(json.dumps(bend, allow_nan=False))
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise KimFormatError('cannot capture project') from error
    doc: dict[str, Any] = {'format': 'kima-assembly', 'version': VERSION,
                           'name': 'Задняя тяга — незавершённый черновик трубы', 'units': 'mm',
                           'frame': 'rear_axle_snapshot', 'scheme': scheme, 'arm': arm,
                           'radius_mm': radius_mm, 'wall_mm': wall_mm,
                           'bend': bend_copy}
    validate_rear_tube(doc)
    return doc


def rear_tube_points(document: dict[str, Any]) -> tuple[tuple[float, float, float], ...]:
    validate_rear_tube(document)
    return make_niva_arm_view(Project.from_dict(document['scheme']), document['arm']).points


def rear_tube_centerline(document: dict[str, Any]) -> tuple[tuple[float, float, float], ...]:
    points = rear_tube_points(document)
    bend = document['bend']
    if bend is None:
        return points
    return make_bend_path(points[0], bend['vertex_mm'], points[1], bend['radius_mm'],
                          document['radius_mm']).sample()
