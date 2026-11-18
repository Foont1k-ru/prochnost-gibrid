"""Информационный код полного снимка сборки, не подпись и не хэш файла."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .kim_format import KimFormatError
from .project_limits import MAX_PROJECT_BYTES
from .scheme_arm_assembly import validate_scheme_arm_assembly


def _normalize_numbers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_numbers(item) for item in value]
    # Python JSON input 12 and 12.0 compares equal in the rest of the editor;
    # likewise -0.0 and 0. Avoid claiming different snapshots in those cases.
    if type(value) is float and value.is_integer():
        return int(value)
    return value


def assembly_snapshot_fingerprint(document: dict[str, Any]) -> str:
    """SHA-256 снимка v1; целочисленные float нормализованы к int.

    Входом служат все данные .kima 0.15/0.16, включая имена и снимок проекта.
    Объекты сортируются по ключам; JSON без пробелов, UTF-8, не ASCII escape.
    Это не хэш исходного файла, не проверка авторства и не сравнение геометрии.
    """
    try:
        validate_scheme_arm_assembly(document)
        normalized = _normalize_numbers(document)
        content = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(content) > MAX_PROJECT_BYTES:
            raise KimFormatError('snapshot exceeds limit')
        return hashlib.sha256(content).hexdigest()
    except KimFormatError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise KimFormatError('cannot fingerprint assembly snapshot') from error
