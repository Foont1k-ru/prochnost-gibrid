"""Защита общей копии между запусками, не замена резервного копирования.

Отпечаток в памяти — разрешение перезаписать только увиденное содержимое.
Параллельные процессы и гонки между проверкой и заменой полностью не исключены.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_AUTOSAVE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AutosaveStamp:
    path: Path
    digest: bytes


def inspect_autosave(path: Path) -> AutosaveStamp | None:
    """None только если файла нет; нестабильные и неподходящие файлы — ошибка."""
    target = path.resolve()
    try:
        before = target.stat()
    except FileNotFoundError:
        if path.is_symlink():
            raise OSError("dangling autosave symlink") from None
        return None
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_AUTOSAVE_BYTES:
        raise OSError("autosave is not a suitable regular file")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        opened_before = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened_before.st_mode) or opened_before.st_size > MAX_AUTOSAVE_BYTES:
            raise OSError("autosave is not a suitable regular file")
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_AUTOSAVE_BYTES:
                raise OSError("autosave too large")
            digest.update(chunk)
        opened_after = os.fstat(stream.fileno())
    after = target.stat()
    if opened_before != opened_after or before != after or size != opened_after.st_size or path.resolve() != target:
        raise OSError("autosave changed while reading")
    return AutosaveStamp(target, digest.digest())


def same_project_file(first: Path, second: Path) -> bool:
    """Обнаружить совпадение пути, симлинка или существующей жёсткой ссылки.

    При ошибке доступа (кроме отсутствия файла) вызывающий код должен отказать.
    Проверка не устраняет гонки изменения путей другими процессами.
    """
    first = first.resolve()
    second = second.resolve()
    if first == second:
        return True
    try:
        first_stat = first.stat()
        second_stat = second.stat()
    except FileNotFoundError:
        return False
    return os.path.samestat(first_stat, second_stat)


class AutosaveGuard:
    def __init__(self) -> None:
        self._approved: AutosaveStamp | None = None

    def may_write(self, current: AutosaveStamp | None) -> bool:
        return current is None or current == self._approved

    def approve(self, expected: AutosaveStamp, actual: AutosaveStamp | None) -> None:
        if actual != expected:
            raise OSError("autosave changed before approval")
        self._approved = expected

    def written(self, stamp: AutosaveStamp | None) -> None:
        if stamp is None:
            raise OSError("autosave disappeared after write")
        self._approved = stamp
