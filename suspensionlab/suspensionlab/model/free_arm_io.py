"""Отдельный формат независимого черновика; никогда не создаёт снимок подвески."""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from .free_arm import FreeArmBend, FreeArmDraft, FreeArmError
from .project_io import ProjectIOError, _read_project_bytes, _unique_object
from .project_limits import MAX_PROJECT_BYTES

SUFFIX = '.slarm'
FORMAT = 'suspensionlab-free-arm'
VERSION = '1'
FRAME = 'independent_xyz'


class FreeArmFileError(ValueError):
    """Не удалось безопасно прочитать или создать независимый черновик."""


def _keys(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise FreeArmFileError('Неверная структура независимого черновика')
    return value


def _bend_data(bend: FreeArmBend | None) -> dict[str, Any] | None:
    return None if bend is None else {'vertex_mm': list(bend.vertex_mm), 'radius_mm': bend.radius_mm}


def to_data(draft: FreeArmDraft) -> dict[str, Any]:
    if not isinstance(draft, FreeArmDraft):
        raise FreeArmFileError('Ожидался независимый черновик')
    return {'format': FORMAT, 'version': VERSION, 'source': 'independent', 'units': 'mm', 'frame': FRAME,
            'anchors_mm': {'front': list(draft.front_mm), 'rear': list(draft.rear_mm), 'outer': list(draft.outer_mm)},
            'tube': {'radius_mm': draft.radius_mm, 'wall_mm': draft.wall_mm},
            'bends': {'front': _bend_data(draft.front_bend), 'rear': _bend_data(draft.rear_bend)}}


def from_data(value: Any) -> FreeArmDraft:
    data = _keys(value, {'format', 'version', 'source', 'units', 'frame', 'anchors_mm', 'tube', 'bends'})
    if (data['format'] != FORMAT or data['version'] != VERSION or data['source'] != 'independent' or
            data['units'] != 'mm' or data['frame'] != FRAME):
        raise FreeArmFileError('Неподдерживаемый формат, источник, версия или система координат')
    anchors = _keys(data['anchors_mm'], {'front', 'rear', 'outer'})
    tube = _keys(data['tube'], {'radius_mm', 'wall_mm'})
    bends = _keys(data['bends'], {'front', 'rear'})

    def make_bend(value: Any) -> FreeArmBend | None:
        if value is None:
            return None
        item = _keys(value, {'vertex_mm', 'radius_mm'})
        return FreeArmBend(item['vertex_mm'], item['radius_mm'])

    try:
        return FreeArmDraft(anchors['front'], anchors['rear'], anchors['outer'], tube['radius_mm'], tube['wall_mm'],
                            make_bend(bends['front']), make_bend(bends['rear']))
    except FreeArmError as error:
        raise FreeArmFileError(f'Недопустимый независимый черновик: {error}') from error


def read_free_arm(path: str | Path) -> FreeArmDraft:
    """Открыть только независимый файл; расчётный .slarm обрабатывается старым кодом."""
    source = Path(path)
    if source.suffix.lower() != SUFFIX:
        raise FreeArmFileError('Ожидался файл .slarm')
    try:
        data = json.loads(_read_project_bytes(source).decode('utf-8'), object_pairs_hook=_unique_object)
        json.dumps(data, allow_nan=False)
        return from_data(data)
    except FreeArmFileError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError, ProjectIOError) as error:
        raise FreeArmFileError('Не удалось прочитать или проверить независимый черновик') from error


def write_free_arm(path: str | Path, draft: FreeArmDraft) -> Path:
    """Записать новый файл атомарным созданием, не заменяя существующий."""
    target = Path(path)
    if target.suffix.lower() != SUFFIX:
        raise FreeArmFileError('Ожидался файл .slarm')
    temporary: str | None = None
    try:
        data = to_data(draft)
        # Revalidate the serialized representation before touching the destination.
        if from_data(data) != draft:
            raise FreeArmFileError('Не удалось проверить независимый черновик')
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(content) > MAX_PROJECT_BYTES:
            raise FreeArmFileError('Файл слишком велик')
        if target.is_symlink():
            raise FreeArmFileError('Символические ссылки не поддерживаются')
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, prefix='.slarm-free-', suffix='.tmp',
                                         delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
        os.unlink(temporary)
        temporary = None
        return target
    except FreeArmFileError:
        raise
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise FreeArmFileError('Не удалось создать новый файл независимого черновика') from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
