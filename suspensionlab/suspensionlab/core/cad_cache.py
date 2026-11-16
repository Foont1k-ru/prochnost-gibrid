"""Небольшой кеш готовых сеток на время одного окна, без записи моделей на диск."""
from __future__ import annotations

import hashlib
import os
import stat
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .cad_mesh import CadMesh
from .cad_transport import CadJob, CadPreviewError
from .step_inventory import MAX_BYTES

CACHE_BYTES = 96 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Fingerprint:
    resolved: str
    digest: bytes


def _stable_stats(first: os.stat_result, after: os.stat_result, path_before: os.stat_result,
                  current: os.stat_result, *, windows: bool) -> bool:
    def identity(item: os.stat_result) -> tuple[int, int, int, int, int]:
        return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns
    # Windows CPython может давать разные inode/ctime у fstat дескриптора и stat
    # пути. Сравниваем каждый источник сам с собой, а между ними лишь размер.
    if identity(first) != identity(after) or identity(path_before) != identity(current):
        return False
    return first.st_size == path_before.st_size and (windows or identity(first) == identity(path_before))


def fingerprint(source: Path, cancelled: Callable[[], bool]) -> Fingerprint | None:
    """Хеш содержимого и проверка обычной замены/правки файла во время чтения.

    Недоступный или неподходящий файл оставляем на обработку CAD-процессу.
    Хеш и путь используются только в памяти, не записываются в отчёты.
    """
    if cancelled():
        raise CadPreviewError("cancelled")
    try:
        resolved = source.resolve(strict=True)
        with resolved.open("rb") as stream:
            descriptor = stream.fileno()
            first = os.fstat(descriptor)
            path_before = source.stat()
            if not stat.S_ISREG(first.st_mode) or not 0 < first.st_size <= MAX_BYTES:
                return None
            digest = hashlib.sha256()
            total = 0
            while chunk := stream.read(1024 * 1024):
                if cancelled():
                    raise CadPreviewError("cancelled")
                total += len(chunk)
                if total > MAX_BYTES:
                    raise CadPreviewError("source_changed")
                digest.update(chunk)
            after = os.fstat(descriptor)
            current = source.stat()
            if total != first.st_size or not _stable_stats(first, after, path_before, current, windows=os.name == "nt"):
                raise CadPreviewError("source_changed")
            if cancelled():
                raise CadPreviewError("cancelled")
            return Fingerprint(str(resolved), digest.digest())
    except OSError:
        return None


def mesh_bytes(mesh: CadMesh) -> int:
    return (mesh.triangles.nbytes +
            (mesh.triangle_parts.nbytes if mesh.triangle_parts is not None else 0) +
            (mesh.triangle_instances.nbytes if mesh.triangle_instances is not None else 0))


class CadMeshCache:
    """LRU одного окна; элементы сверх бюджета не кешируются."""

    def __init__(self, budget: int = CACHE_BYTES) -> None:
        if budget < 0:
            raise ValueError("budget")
        self.budget = budget
        self._bytes = 0
        self._items: OrderedDict[tuple[Fingerprint, float], CadMesh] = OrderedDict()

    def get(self, key: tuple[Fingerprint, float]) -> CadMesh | None:
        mesh = self._items.get(key)
        if mesh is not None:
            self._items.move_to_end(key)
        return mesh

    def put(self, key: tuple[Fingerprint, float], mesh: CadMesh) -> None:
        old = self._items.pop(key, None)
        if old is not None:
            self._bytes -= mesh_bytes(old)
        size = mesh_bytes(mesh)
        if size > self.budget:
            return
        while self._items and self._bytes + size > self.budget:
            _, removed = self._items.popitem(last=False)
            self._bytes -= mesh_bytes(removed)
        self._items[key] = mesh
        self._bytes += size

    def run(self, job: CadJob, source: Path, deviation: float, *, force: bool = False) -> tuple[CadMesh, bool]:
        if job.progress_callback is not None:
            job.progress_callback("fingerprint", 0)
        first = fingerprint(source, job.is_cancelled)
        key = (first, deviation) if first is not None else None
        if key is not None and not force:
            cached = self.get(key)
            if cached is not None:
                if job.is_cancelled():
                    raise CadPreviewError("cancelled")
                return cached, True
        mesh = job.run(source, deviation)
        if job.is_cancelled():
            raise CadPreviewError("cancelled")
        if first is not None:
            if job.progress_callback is not None:
                job.progress_callback("fingerprint", 0)
            second = fingerprint(source, job.is_cancelled)
            if first != second:
                raise CadPreviewError("source_changed")
            assert key is not None
            self.put(key, mesh)
        return mesh, False
