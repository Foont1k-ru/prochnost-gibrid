"""Версия 3 независимого .slarm с корпусами внутренних опор.

Отдельный читатель: старые редакторы v1/v2 должны отказаться от v3, а не потерять
корпуса при открытии/записи. Версия не содержит проекта и расчётного снимка.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from .fixed_arm_housings import HousingError
from .free_arm_housing import FreeArmBallHousing, FreeArmHousingError
from .free_arm_inner_housings import FreeArmInnerHousingDraft, FreeArmInnerHousings
from .free_arm_io import FORMAT, SUFFIX, FreeArmFileError
from .free_arm_io import from_data as arm_from_data
from .free_arm_io import to_data as arm_to_data
from .project_io import ProjectIOError, _read_project_bytes, _unique_object
from .project_limits import MAX_PROJECT_BYTES

VERSION = '3'


class FreeArmInnerHousingFileError(FreeArmFileError):
    """Файл независимого рычага с корпусом не прошёл проверку."""


def to_data(draft: FreeArmInnerHousingDraft) -> dict[str, Any]:
    if not isinstance(draft, FreeArmInnerHousingDraft):
        raise FreeArmInnerHousingFileError('Ожидался независимый рычаг с корпусом')
    data = arm_to_data(draft.arm)
    data['version'] = VERSION
    data['ball_housing'] = draft.ball_housing.as_data() if draft.ball_housing is not None else None
    data['inner_housings'] = draft.housings.as_housings()
    data['notches'] = draft.housings.as_notches()
    return data


def from_data(value: Any) -> FreeArmInnerHousingDraft:
    keys = {'format', 'version', 'source', 'units', 'frame', 'anchors_mm', 'tube', 'bends', 'ball_housing', 'inner_housings', 'notches'}
    if not isinstance(value, dict) or set(value) != keys or value['format'] != FORMAT or value['version'] != VERSION:
        raise FreeArmInnerHousingFileError('Неверная структура или версия независимого корпуса')
    arm_data = {key: val for key, val in value.items() if key not in ('ball_housing', 'inner_housings', 'notches')}
    arm_data['version'] = '1'
    try:
        return FreeArmInnerHousingDraft(arm_from_data(arm_data),
                                        FreeArmInnerHousings.from_data(value['inner_housings'], value['notches']),
                                        FreeArmBallHousing.from_data(value['ball_housing'])
                                        if value['ball_housing'] is not None else None)
    except (FreeArmFileError, FreeArmHousingError, HousingError) as error:
        raise FreeArmInnerHousingFileError(f'Недопустимый независимый рычаг с корпусом: {error}') from error


def read_free_arm_inner_housings(path: str | Path) -> FreeArmInnerHousingDraft:
    source = Path(path)
    if source.suffix.lower() != SUFFIX:
        raise FreeArmInnerHousingFileError('Ожидался файл .slarm')
    try:
        data = json.loads(_read_project_bytes(source).decode('utf-8'), object_pairs_hook=_unique_object)
        json.dumps(data, allow_nan=False)
        return from_data(data)
    except FreeArmInnerHousingFileError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError, ProjectIOError) as error:
        raise FreeArmInnerHousingFileError('Не удалось прочитать или проверить независимый корпус') from error


def write_free_arm_inner_housings(path: str | Path, draft: FreeArmInnerHousingDraft) -> Path:
    """Атомарное создание нового файла без перезаписи, как в независимом v1."""
    target = Path(path)
    if target.suffix.lower() != SUFFIX:
        raise FreeArmInnerHousingFileError('Ожидался файл .slarm')
    temporary: str | None = None
    try:
        data = to_data(draft)
        if from_data(data) != draft:
            raise FreeArmInnerHousingFileError('Не удалось проверить независимый корпус')
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(content) > MAX_PROJECT_BYTES:
            raise FreeArmInnerHousingFileError('Файл слишком велик')
        if target.is_symlink():
            raise FreeArmInnerHousingFileError('Символические ссылки не поддерживаются')
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
    except FreeArmInnerHousingFileError:
        raise
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise FreeArmInnerHousingFileError('Не удалось создать независимый файл с корпусом') from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
