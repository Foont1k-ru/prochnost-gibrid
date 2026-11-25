"""Версия 5 независимого .slarm с односторонней подрезкой трубы.

Старые читатели v1–v4 отказывают на v5, а не отбрасывают подрезку. Версия не содержит проекта и расчётного снимка.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from .fixed_arm_housings import HousingError, validate_tube_joint
from .free_arm_inner_housings import FreeArmInnerHousings
from .free_arm_io import FORMAT, SUFFIX, FreeArmFileError
from .free_arm_io import from_data as arm_from_data
from .free_arm_io import to_data as arm_to_data
from .free_arm_tube_joint import FreeArmTubeJoint, FreeArmTubeJointDraft
from .project_io import ProjectIOError, _read_project_bytes, _unique_object
from .project_limits import MAX_PROJECT_BYTES

VERSION = '5'


class FreeArmTubeJointFileError(FreeArmFileError):
    """Файл независимого рычага с подрезкой не прошёл проверку."""


def to_data(draft: FreeArmTubeJointDraft) -> dict[str, Any]:
    if not isinstance(draft, FreeArmTubeJointDraft):
        raise FreeArmTubeJointFileError('Ожидался независимый рычаг с подрезкой трубы')
    data = arm_to_data(draft.arm)
    data['version'] = VERSION
    data['joint'] = draft.joint.as_data()
    data['inner_housings'] = draft.housings.as_housings() if draft.housings is not None else None
    data['notches'] = draft.housings.as_notches() if draft.housings is not None else None
    return data


def from_data(value: Any) -> FreeArmTubeJointDraft:
    keys = {'format', 'version', 'source', 'units', 'frame', 'anchors_mm', 'tube', 'bends', 'joint', 'inner_housings', 'notches'}
    if not isinstance(value, dict) or set(value) != keys or value['format'] != FORMAT or value['version'] != VERSION:
        raise FreeArmTubeJointFileError('Неверная структура или версия независимой подрезки')
    if value['inner_housings'] is None and value['notches'] is not None:
        raise FreeArmTubeJointFileError('Подрезка требует внутренних корпусов')
    arm_data = {key: val for key, val in value.items() if key not in ('joint', 'inner_housings', 'notches')}
    arm_data['version'] = '1'
    try:
        joint = validate_tube_joint(value['joint'])
        inner = (FreeArmInnerHousings.from_data(value['inner_housings'], value['notches'])
                 if value['inner_housings'] is not None else None)
        return FreeArmTubeJointDraft(arm_from_data(arm_data),
                                     FreeArmTubeJoint(joint['target'], joint['radial_clearance_mm']), inner)
    except (FreeArmFileError, HousingError) as error:
        raise FreeArmTubeJointFileError(f'Недопустимый независимый рычаг с подрезкой: {error}') from error


def read_free_arm_tube_joint(path: str | Path) -> FreeArmTubeJointDraft:
    source = Path(path)
    if source.suffix.lower() != SUFFIX:
        raise FreeArmTubeJointFileError('Ожидался файл .slarm')
    try:
        data = json.loads(_read_project_bytes(source).decode('utf-8'), object_pairs_hook=_unique_object)
        json.dumps(data, allow_nan=False)
        return from_data(data)
    except FreeArmTubeJointFileError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError, ProjectIOError) as error:
        raise FreeArmTubeJointFileError('Не удалось прочитать или проверить независимую подрезку') from error


def write_free_arm_tube_joint(path: str | Path, draft: FreeArmTubeJointDraft) -> Path:
    """Атомарное создание нового файла без перезаписи, как в независимом v1."""
    target = Path(path)
    if target.suffix.lower() != SUFFIX:
        raise FreeArmTubeJointFileError('Ожидался файл .slarm')
    temporary: str | None = None
    try:
        data = to_data(draft)
        if from_data(data) != draft:
            raise FreeArmTubeJointFileError('Не удалось проверить независимую подрезку')
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(content) > MAX_PROJECT_BYTES:
            raise FreeArmTubeJointFileError('Файл слишком велик')
        if target.is_symlink():
            raise FreeArmTubeJointFileError('Символические ссылки не поддерживаются')
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
    except FreeArmTubeJointFileError:
        raise
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise FreeArmTubeJointFileError('Не удалось создать независимый файл с подрезкой') from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
