"""Защита общей копии между запусками, не замена резервного копирования.

Отпечаток в памяти — разрешение перезаписать только увиденное содержимое.
Совместимые процессы координируют запись отдельной блокировкой; внешние
программы, старые версии и некоторые файловые системы могут её игнорировать.
"""
from __future__ import annotations

import errno
import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

MAX_AUTOSAVE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AutosaveStamp:
    path: Path
    digest: bytes


def _stable_metadata(value: os.stat_result) -> tuple[int, ...]:
    # Access time can change solely because this function reads the file.
    # Compare each stat source with itself (Windows fstat and stat may differ).
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


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
    if (_stable_metadata(opened_before) != _stable_metadata(opened_after) or
            _stable_metadata(before) != _stable_metadata(after) or
            size != opened_after.st_size or path.resolve() != target):
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


class AutosaveBusyError(OSError):
    """Другой совместимый процесс в данный момент записывает общую копию."""


@contextmanager
def autosave_write_lock(path: Path) -> Iterator[None]:
    """Неблокирующая межпроцессная блокировка всего цикла проверки и записи.

    Стабильный sidecar не удаляется: удаление открытого файла разрушает
    координацию на POSIX. Блокировка освобождается ОС при завершении процесса.
    Это добровольная блокировка, внешние программы могут её игнорировать.
    """
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lockfile = target.with_name(target.name + ".lock")
    if lockfile.is_symlink():
        raise OSError("autosave lock is a symlink")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lockfile, flags, 0o600)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or lockfile.is_symlink():
            raise OSError("invalid autosave lock")
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
            locked = True
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise AutosaveBusyError("autosave lock is held") from error
            raise
        yield
    finally:
        try:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
        finally:
            os.close(fd)


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
