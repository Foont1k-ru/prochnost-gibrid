"""Отдельный экспериментальный файл скелета; загрузка только с пересчётом.

Сохранение только в новый файл. Файл не является проектом, CAD или сертификатом.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .entities import Project
from .fixed_arm_housings import HousingError, validate_housings, validate_notches
from .fixed_arm_skeleton import FixedArmSnapshot, SkeletonError, capture_fixed_arm, preview_fixed_arm
from .fixed_arm_skeleton import _raw_points as _current_raw_points
from .project_io import ProjectIOError, _read_project_bytes, _unique_object
from .project_limits import MAX_PROJECT_BYTES

SUFFIX = '.slarm'
_FORMAT = 'suspensionlab-fixed-arm-skeleton'
_VERSION = '1'
_ALGORITHM = 'double-wishbone-left-fixed-rack-continuation-v1'


class SkeletonFileError(ValueError):
    """Файл недоступен, не соответствует проекту или не прошёл пересчёт."""


@dataclass(frozen=True, slots=True)
class LoadedSkeleton:
    snapshot: FixedArmSnapshot
    radius_mm: float
    wall_mm: float
    bends: dict[str, dict[str, Any]]
    recorded_residual_mm: float
    housings: dict[str, Any] | None = None
    notches: dict[str, float] | None = None


def _keys(value: Any, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise SkeletonFileError('Неверная структура файла скелета')
    return value


def _number(value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SkeletonFileError('Ожидалось конечное число')
    try:
        number = float(value)
    except OverflowError as error:
        raise SkeletonFileError('Число вне диапазона') from error
    if not math.isfinite(number) or not low <= number <= high:
        raise SkeletonFileError('Число вне диапазона')
    return number


def _ui_number(value: Any, low: float, high: float) -> float:
    number = _number(value, low, high)
    if round(number, 2) != number:
        raise SkeletonFileError('Точность параметра не поддерживается редактором')
    return number


def _bends(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or any(key not in ('front', 'rear') for key in value):
        raise SkeletonFileError('Неверные параметры изгибов')
    result: dict[str, dict[str, Any]] = {}
    for leg, bend in value.items():
        item = _keys(bend, {'vertex_mm', 'radius_mm'})
        vertex = item['vertex_mm']
        if not isinstance(vertex, list) or len(vertex) != 3:
            raise SkeletonFileError('Неверная вершина изгиба')
        result[leg] = {'vertex_mm': [_number(v, -1_000_000, 1_000_000) for v in vertex],
                       'radius_mm': _number(item['radius_mm'], 0.01, 1_000_000)}
    return result


def _raw_points(value: Any) -> tuple[tuple[float, float, float], ...]:
    if not isinstance(value, list) or len(value) != 9:
        raise SkeletonFileError('Неверные исходные точки решателя')
    result = []
    for p in value:
        if not isinstance(p, list) or len(p) != 3:
            raise SkeletonFileError('Неверные исходные точки решателя')
        result.append((_number(p[0], -1_000_000, 1_000_000), _number(p[1], -1_000_000, 1_000_000),
                       _number(p[2], -1_000_000, 1_000_000)))
    return tuple(result)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _recheck(data: Any, current: Project) -> LoadedSkeleton:
    doc = _keys(data, {'format', 'version', 'units', 'frame', 'project', 'raw_solver_points', 'calculation', 'geometry'})
    if (doc['format'] != _FORMAT or doc['version'] not in (_VERSION, '2', '3') or doc['units'] != 'mm' or
            doc['frame'] != 'vehicle_front_left'):
        raise SkeletonFileError('Неподдерживаемый формат, версия или система координат')
    calc = _keys(doc['calculation'], {'algorithm', 'from_mm', 'to_mm', 'spacing_mm', 'max_step_mm',
                                      'travels_mm', 'max_residual_mm'})
    if calc['algorithm'] != _ALGORITHM:
        raise SkeletonFileError('Неподдерживаемый алгоритм расчёта')
    low = _ui_number(calc['from_mm'], -250, 0)
    high = _ui_number(calc['to_mm'], 0, 250)
    spacing = _ui_number(calc['spacing_mm'], 1, 50)
    max_step = _number(calc['max_step_mm'], 0.1, 2)
    old_residual = _number(calc['max_residual_mm'], 0, 1)
    if not isinstance(calc['travels_mm'], list) or not 1 <= len(calc['travels_mm']) <= 501:
        raise SkeletonFileError('Неверная сетка расчёта')
    travels = [_number(x, -250, 250) for x in calc['travels_mm']]
    geometry_keys = {'radius_mm', 'wall_mm', 'bends'}
    if doc['version'] in ('2', '3'):
        geometry_keys.add('housings')
    if doc['version'] == '3':
        geometry_keys.add('notches')
    geom = _keys(doc['geometry'], geometry_keys)
    try:
        housings = validate_housings(geom['housings']) if doc['version'] in ('2', '3') else None
        notches = validate_notches(geom['notches']) if doc['version'] == '3' else None
    except HousingError as error:
        raise SkeletonFileError(f'Неверные параметры корпусов или подрезки: {error}') from error
    radius = _ui_number(geom['radius_mm'], 0.01, 10000)
    wall = _ui_number(geom['wall_mm'], 0.01, 10000)
    bends = _bends(geom['bends'])
    raw = _raw_points(doc['raw_solver_points'])
    # Never load the untrusted embedded project into the application. The file
    # must match the open project before any solver or geometry reconstruction.
    from .project_io import project_to_json

    if _canonical(doc['project']) != _canonical(json.loads(project_to_json(current))):
        raise SkeletonFileError('Файл относится к другой или изменённой схеме; автоматической привязки нет')
    try:
        if _current_raw_points(current) != raw:
            raise SkeletonFileError('Точные исходные координаты изменились; необходим новый снимок')
        snapshot = capture_fixed_arm(current, low, high, spacing_mm=spacing, max_step_mm=max_step)
        if snapshot.raw_solver_points != raw:
            raise SkeletonFileError('Точные исходные координаты изменились во время расчёта')
        if list(snapshot.travels_mm) != travels:
            raise SkeletonFileError('Сетка файла не соответствует указанным условиям')
        preview_fixed_arm(snapshot, current, radius, wall, bends)
    except SkeletonError as error:
        raise SkeletonFileError(f'Повторный расчёт или построение не выполнены: {error}') from error
    return LoadedSkeleton(snapshot, radius, wall, bends, old_residual, housings, notches)


def make_skeleton_data(snapshot: FixedArmSnapshot, current: Project, radius_mm: float, wall_mm: float,
                       bends: dict[str, dict[str, Any]], housings: dict[str, Any] | None = None,
                       notches: dict[str, float] | None = None) -> dict[str, Any]:
    """Проверка актуальности, геометрии и повторный расчёт перед записью."""
    if not snapshot.matches(current):
        raise SkeletonFileError('Проект отличается от снимка')
    if notches is not None and housings is None:
        raise SkeletonFileError('Для подрезки необходимы корпуса')
    data: dict[str, Any] = {
        'format': _FORMAT, 'version': '3' if notches is not None else '2' if housings is not None else _VERSION,
        'units': 'mm', 'frame': 'vehicle_front_left',
        'project': json.loads(snapshot.project_json),
        'raw_solver_points': [list(p) for p in snapshot.raw_solver_points],
        'calculation': {'algorithm': _ALGORITHM, 'from_mm': snapshot.travels_mm[0],
                        'to_mm': snapshot.travels_mm[-1], 'spacing_mm': snapshot.spacing_mm,
                        'max_step_mm': snapshot.max_step_mm, 'travels_mm': list(snapshot.travels_mm),
                        'max_residual_mm': snapshot.max_residual_mm},
        'geometry': {'radius_mm': radius_mm, 'wall_mm': wall_mm, 'bends': bends},
    }
    if housings is not None:
        data['geometry']['housings'] = housings
    if notches is not None:
        data['geometry']['notches'] = notches
    checked = _recheck(data, current)
    if checked.snapshot != snapshot:
        raise SkeletonFileError('Расчётный снимок изменился; требуется новая фиксация')
    # Return a detached copy of all mutable input data.
    return json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))


def read_skeleton(path: str | Path, current: Project) -> LoadedSkeleton:
    """Прочитать и пересчитать; не модифицирует проект или существующие файлы."""
    source = Path(path)
    try:
        if source.suffix.lower() != SUFFIX:
            raise SkeletonFileError('Ожидался файл .slarm')
        data = json.loads(_read_project_bytes(source).decode('utf-8'), object_pairs_hook=_unique_object)
        # Reject non-finite values even in fields which will later be rejected.
        json.dumps(data, allow_nan=False)
        return _recheck(data, current)
    except SkeletonFileError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, OverflowError, ProjectIOError) as error:
        raise SkeletonFileError('Не удалось прочитать или проверить файл скелета') from error


def write_skeleton(path: str | Path, snapshot: FixedArmSnapshot, current: Project, radius_mm: float,
                   wall_mm: float, bends: dict[str, dict[str, Any]], housings: dict[str, Any] | None = None,
                   notches: dict[str, float] | None = None) -> Path:
    """Записать новый файл атомарным созданием без перезаписи и без ссылок."""
    target = Path(path)
    if target.suffix.lower() != SUFFIX:
        raise SkeletonFileError('Ожидался файл .slarm')
    temporary: str | None = None
    try:
        data = make_skeleton_data(snapshot, current, radius_mm, wall_mm, bends, housings, notches)
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(content) > MAX_PROJECT_BYTES:
            raise SkeletonFileError('Файл слишком велик')
        if target.is_symlink():
            raise SkeletonFileError('Символические ссылки не поддерживаются')
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, prefix='.slarm-', suffix='.tmp',
                                         delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if not snapshot.matches(current):
            raise SkeletonFileError('Проект изменился во время записи')
        # Also catches an existing symlink or file created while writing.
        os.link(temporary, target)
        os.unlink(temporary)
        temporary = None
        return target
    except SkeletonFileError:
        raise
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise SkeletonFileError('Не удалось создать новый файл скелета') from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
