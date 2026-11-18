"""Неполная сборка рычага: два отдельных .kim труб и два корпуса, без сварки."""
from __future__ import annotations

import copy
import json
from typing import Any

from .entities import Project
from .kim_format import (
    HOUSING_PART_VERSION,
    KimFormatError,
    _keys,
    _lower_arm_source,
    _name,
    _part,
    _scheme,
    make_arm_tube,
)
from .project_io import project_to_json

VERSION = '0.15'
ALGORITHM = 'front_lower_left_assembly_v1'
PARTS = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
UNRESOLVED = ['ball_bracket', 'ball_joint', 'silent_blocks', 'fasteners', 'welds']


def make_housing(identifier: str, name: str, outer: float, bore: float, length: float) -> dict[str, Any]:
    """Отдельный корпус в локальных координатах, центр (0,0,0), ось Z."""
    doc = {'format': 'kim-part', 'version': HOUSING_PART_VERSION, 'id': identifier, 'name': name, 'units': 'mm',
           'geometry': {'kind': 'prototype_bushing_housing', 'outer_radius_mm': outer,
                        'bore_radius_mm': bore, 'length_mm': length}}
    _part(doc)
    return doc


def validate_scheme_arm_assembly(value: Any) -> None:
    doc = _keys(value, {'format', 'version', 'algorithm', 'name', 'units', 'frame', 'scheme',
                        'axis', 'parts', 'unresolved'})
    if (doc['format'] != 'kima-assembly' or doc['version'] != VERSION or doc['algorithm'] != ALGORITHM or
            doc['units'] != 'mm' or doc['frame'] != 'vehicle_front_left_snapshot'):
        raise KimFormatError('unsupported scheme arm assembly')
    _name(doc['name'])
    if doc['scheme'] is None:
        raise KimFormatError('scheme is required')
    _scheme(doc['scheme'])
    if doc['axis'] not in ('x', 'y', 'z') or doc['unresolved'] != UNRESOLVED:
        raise KimFormatError('invalid axis or incomplete assembly declaration')
    parts = doc['parts']
    if not isinstance(parts, list) or len(parts) != 4:
        raise KimFormatError('four independent parts required')
    for index, identifier in enumerate(PARTS):
        part = parts[index]
        _part(part)
        if part['id'] != identifier:
            raise KimFormatError('invalid part identity or order')
        geometry = part['geometry']
        if index < 2:
            if (part['version'] != '0.1' or geometry['kind'] != 'prototype_arm_tube' or
                    geometry['leg'] != ('front' if index == 0 else 'rear') or
                    geometry['radius_mm'] > 10000 or geometry['wall_mm'] > 10000 or
                    geometry['source'] != _lower_arm_source(Project.from_dict(doc['scheme']))):
                raise KimFormatError('tube and scheme do not match')
        elif part['version'] != HOUSING_PART_VERSION:
            raise KimFormatError('housing part required')


def make_scheme_arm_assembly(project: Project, radius: float, wall: float,
                             bushings: dict[str, Any]) -> dict[str, Any]:
    """Самодостаточные снимки деталей: координаты труб в кузове, корпусов локальные."""
    try:
        data = _keys(bushings, {'axis', 'outer_radius_mm', 'bore_radius_mm', 'length_mm'})
        scheme = json.loads(project_to_json(project))
        snapshot = Project.from_dict(scheme)
        parts = [make_arm_tube('tube_front', 'Передняя труба', snapshot, 'front', radius, wall),
                 make_arm_tube('tube_rear', 'Задняя труба', snapshot, 'rear', radius, wall),
                 make_housing('housing_front', 'Передний корпус втулки', data['outer_radius_mm'],
                              data['bore_radius_mm'], data['length_mm']),
                 make_housing('housing_rear', 'Задний корпус втулки', data['outer_radius_mm'],
                              data['bore_radius_mm'], data['length_mm'])]
        doc = {'format': 'kima-assembly', 'version': VERSION, 'algorithm': ALGORITHM,
               'name': 'Передний нижний левый рычаг — предварительная сборка', 'units': 'mm',
               'frame': 'vehicle_front_left_snapshot', 'scheme': scheme, 'axis': data['axis'],
               'parts': parts, 'unresolved': list(UNRESOLVED)}
        validate_scheme_arm_assembly(doc)
        return doc
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise KimFormatError('cannot create preliminary arm assembly') from error


def rebuild_scheme_arm_assembly(document: dict[str, Any], project: Project) -> dict[str, Any]:
    """Явно заменить схему, сохранив отдельные детали и все их известные параметры."""
    validate_scheme_arm_assembly(document)
    if _lower_arm_source(project)['suspension_type'] != document['parts'][0]['geometry']['source']['suspension_type']:
        raise KimFormatError('suspension type changed')
    result = copy.deepcopy(document)
    try:
        result['scheme'] = json.loads(project_to_json(project))
        snapshot = Project.from_dict(result['scheme'])
        for index, leg in enumerate(('front', 'rear')):
            part = document['parts'][index]
            geom = part['geometry']
            result['parts'][index] = make_arm_tube(part['id'], part['name'], snapshot, leg,
                                                   geom['radius_mm'], geom['wall_mm'])
        validate_scheme_arm_assembly(result)
        return result
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise KimFormatError('cannot rebuild assembly') from error


def replace_assembly_part(document: dict[str, Any], identifier: str, part: dict[str, Any]) -> dict[str, Any]:
    """Вставить копию одной совместимой детали в указанную позицию; исходники не менять.

    Идентификатор внутри сборки принадлежит позиции. При замене он явно
    привязывается к ней; данные геометрии и имя импортированного снимка сохраняются.
    Для трубы тип, сторона и три точки должны совпадать со снимком схемы.
    """
    validate_scheme_arm_assembly(document)
    if identifier not in PARTS:
        raise KimFormatError('unknown part position')
    _part(part)
    result = copy.deepcopy(document)
    replacement = copy.deepcopy(part)
    replacement['id'] = identifier
    result['parts'][PARTS.index(identifier)] = replacement
    validate_scheme_arm_assembly(result)
    return result


def edit_assembly_part(document: dict[str, Any], identifier: str, dimensions: dict[str, Any]) -> dict[str, Any]:
    """Изменить только размеры выбранной детали, без сброса других данных."""
    validate_scheme_arm_assembly(document)
    if identifier not in PARTS:
        raise KimFormatError('unknown part position')
    keys = ({'radius_mm', 'wall_mm'} if identifier in PARTS[:2] else
            {'outer_radius_mm', 'bore_radius_mm', 'length_mm'})
    _keys(dimensions, keys)
    part = copy.deepcopy(document['parts'][PARTS.index(identifier)])
    part['geometry'].update(copy.deepcopy(dimensions))
    return replace_assembly_part(document, identifier, part)


def set_assembly_axis(document: dict[str, Any], axis: str) -> dict[str, Any]:
    """Общая ось размещения корпусов в координатах кузова, без изменений деталей."""
    validate_scheme_arm_assembly(document)
    result = copy.deepcopy(document)
    result['axis'] = axis
    validate_scheme_arm_assembly(result)
    return result
