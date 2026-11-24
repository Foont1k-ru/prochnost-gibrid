"""Версия 2 независимого .slarm с центральным корпусом.

Отдельный читатель: старый редактор v1 должен отказаться от v2, а не потерять
корпус при открытии/записи. Версия не содержит проекта и расчётного снимка.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .free_arm_inner_housings import FreeArmInnerHousingDraft
    from .free_arm_miter import FreeArmMiterDraft
    from .free_arm_tube_joint import FreeArmTubeJointDraft

from .free_arm import FreeArmDraft
from .free_arm_housing import FreeArmBallHousing, FreeArmHousingDraft, FreeArmHousingError
from .free_arm_io import FORMAT, SUFFIX, FreeArmFileError
from .free_arm_io import from_data as arm_from_data
from .free_arm_io import to_data as arm_to_data
from .project_io import ProjectIOError, _read_project_bytes, _unique_object
from .project_limits import MAX_PROJECT_BYTES

VERSION = '2'


class FreeArmHousingFileError(FreeArmFileError):
    """Файл независимого рычага с корпусом не прошёл проверку."""


def to_data(draft: FreeArmHousingDraft) -> dict[str, Any]:
    if not isinstance(draft, FreeArmHousingDraft):
        raise FreeArmHousingFileError('Ожидался независимый рычаг с корпусом')
    data = arm_to_data(draft.arm)
    data['version'] = VERSION
    data['ball_housing'] = draft.housing.as_data()
    return data


def from_data(value: Any) -> FreeArmHousingDraft:
    keys = {'format', 'version', 'source', 'units', 'frame', 'anchors_mm', 'tube', 'bends', 'ball_housing'}
    if not isinstance(value, dict) or set(value) != keys or value['format'] != FORMAT or value['version'] != VERSION:
        raise FreeArmHousingFileError('Неверная структура или версия независимого корпуса')
    arm_data = {key: val for key, val in value.items() if key != 'ball_housing'}
    arm_data['version'] = '1'
    try:
        return FreeArmHousingDraft(arm_from_data(arm_data), FreeArmBallHousing.from_data(value['ball_housing']))
    except (FreeArmFileError, FreeArmHousingError) as error:
        raise FreeArmHousingFileError(f'Недопустимый независимый рычаг с корпусом: {error}') from error


def read_free_arm_housing(path: str | Path) -> FreeArmHousingDraft:
    source = Path(path)
    if source.suffix.lower() != SUFFIX:
        raise FreeArmHousingFileError('Ожидался файл .slarm')
    try:
        data = json.loads(_read_project_bytes(source).decode('utf-8'), object_pairs_hook=_unique_object)
        json.dumps(data, allow_nan=False)
        return from_data(data)
    except FreeArmHousingFileError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError, ProjectIOError) as error:
        raise FreeArmHousingFileError('Не удалось прочитать или проверить независимый корпус') from error


def read_independent_arm(path: str | Path) -> FreeArmDraft | FreeArmHousingDraft | FreeArmInnerHousingDraft | FreeArmMiterDraft | FreeArmTubeJointDraft:
    """Прочитать один снимок файла и строго выбрать поддерживаемую версию без потери данных."""
    from .free_arm_inner_housings_io import from_data as inner_from_data
    from .free_arm_miter_io import from_data as miter_from_data
    from .free_arm_tube_joint_io import from_data as joint_from_data
    source = Path(path)
    if source.suffix.lower() != SUFFIX:
        raise FreeArmFileError('Ожидался файл .slarm')
    try:
        data = json.loads(_read_project_bytes(source).decode('utf-8'), object_pairs_hook=_unique_object)
        json.dumps(data, allow_nan=False)
        if isinstance(data, dict) and data.get('version') == VERSION:
            return from_data(data)
        if isinstance(data, dict) and data.get('version') == '3':
            return inner_from_data(data)
        if isinstance(data, dict) and data.get('version') == '4':
            return miter_from_data(data)
        if isinstance(data, dict) and data.get('version') == '5':
            return joint_from_data(data)
        return arm_from_data(data)
    except FreeArmFileError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError, ProjectIOError) as error:
        raise FreeArmFileError('Не удалось прочитать или проверить независимый черновик') from error


def write_free_arm_housing(path: str | Path, draft: FreeArmHousingDraft) -> Path:
    """Атомарное создание нового файла без перезаписи, как в независимом v1."""
    target = Path(path)
    if target.suffix.lower() != SUFFIX:
        raise FreeArmHousingFileError('Ожидался файл .slarm')
    temporary: str | None = None
    try:
        data = to_data(draft)
        if from_data(data) != draft:
            raise FreeArmHousingFileError('Не удалось проверить независимый корпус')
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(content) > MAX_PROJECT_BYTES:
            raise FreeArmHousingFileError('Файл слишком велик')
        if target.is_symlink():
            raise FreeArmHousingFileError('Символические ссылки не поддерживаются')
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
    except FreeArmHousingFileError:
        raise
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise FreeArmHousingFileError('Не удалось создать независимый файл с корпусом') from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
