"""Версия 4 независимого .slarm с общим стыком на ус.

Старые читатели v1–v3 отказывают на v4, а не отбрасывают общий стык. Версия не содержит проекта и расчётного снимка.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from .fixed_arm_housings import HousingError
from .free_arm_inner_housings import FreeArmInnerHousings
from .free_arm_io import FORMAT, SUFFIX, FreeArmFileError
from .free_arm_io import from_data as arm_from_data
from .free_arm_io import to_data as arm_to_data
from .free_arm_miter import FreeArmMiterDraft, FreeArmMiterError
from .project_io import ProjectIOError, _read_project_bytes, _unique_object
from .project_limits import MAX_PROJECT_BYTES

VERSION = '4'


class FreeArmMiterFileError(FreeArmFileError):
    """Файл независимого рычага со стыком не прошёл проверку."""


def to_data(draft: FreeArmMiterDraft) -> dict[str, Any]:
    if not isinstance(draft, FreeArmMiterDraft):
        raise FreeArmMiterFileError('Ожидался независимый рычаг со стыком на ус')
    data = arm_to_data(draft.arm)
    data['version'] = VERSION
    data['joint'] = {'target': 'miter', 'radial_clearance_mm': 0.}
    data['inner_housings'] = draft.housings.as_housings() if draft.housings is not None else None
    data['notches'] = draft.housings.as_notches() if draft.housings is not None else None
    return data


def from_data(value: Any) -> FreeArmMiterDraft:
    keys = {'format', 'version', 'source', 'units', 'frame', 'anchors_mm', 'tube', 'bends', 'joint', 'inner_housings', 'notches'}
    if not isinstance(value, dict) or set(value) != keys or value['format'] != FORMAT or value['version'] != VERSION:
        raise FreeArmMiterFileError('Неверная структура или версия независимого стыка')
    joint = value['joint']
    if (not isinstance(joint, dict) or set(joint) != {'target', 'radial_clearance_mm'} or
            joint['target'] != 'miter' or type(joint['radial_clearance_mm']) not in (int, float) or
            joint['radial_clearance_mm'] != 0):
        raise FreeArmMiterFileError('Общий стык допускает только нулевой зазор')
    if value['inner_housings'] is None and value['notches'] is not None:
        raise FreeArmMiterFileError('Подрезка требует внутренних корпусов')
    arm_data = {key: val for key, val in value.items() if key not in ('joint', 'inner_housings', 'notches')}
    arm_data['version'] = '1'
    try:
        inner = (FreeArmInnerHousings.from_data(value['inner_housings'], value['notches'])
                 if value['inner_housings'] is not None else None)
        return FreeArmMiterDraft(arm_from_data(arm_data), inner)
    except (FreeArmFileError, FreeArmMiterError, HousingError) as error:
        raise FreeArmMiterFileError(f'Недопустимый независимый рычаг со стыком: {error}') from error


def read_free_arm_miter(path: str | Path) -> FreeArmMiterDraft:
    source = Path(path)
    if source.suffix.lower() != SUFFIX:
        raise FreeArmMiterFileError('Ожидался файл .slarm')
    try:
        data = json.loads(_read_project_bytes(source).decode('utf-8'), object_pairs_hook=_unique_object)
        json.dumps(data, allow_nan=False)
        return from_data(data)
    except FreeArmMiterFileError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError, ProjectIOError) as error:
        raise FreeArmMiterFileError('Не удалось прочитать или проверить независимый стык') from error


def write_free_arm_miter(path: str | Path, draft: FreeArmMiterDraft) -> Path:
    """Атомарное создание нового файла без перезаписи, как в независимом v1."""
    target = Path(path)
    if target.suffix.lower() != SUFFIX:
        raise FreeArmMiterFileError('Ожидался файл .slarm')
    temporary: str | None = None
    try:
        data = to_data(draft)
        if from_data(data) != draft:
            raise FreeArmMiterFileError('Не удалось проверить независимый стык')
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(content) > MAX_PROJECT_BYTES:
            raise FreeArmMiterFileError('Файл слишком велик')
        if target.is_symlink():
            raise FreeArmMiterFileError('Символические ссылки не поддерживаются')
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
    except FreeArmMiterFileError:
        raise
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise FreeArmMiterFileError('Не удалось создать независимый файл со стыком') from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
