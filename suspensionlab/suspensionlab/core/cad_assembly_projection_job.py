"""Ограниченный отменяемый процесс построения линий предварительной сборки."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..model.kim_format import write_document
from .cad_assembly_projection import MAX_COORDINATE, MAX_SEGMENTS, PLANES
from .cad_transport import CadPreviewError

MAX_OUTPUT_BYTES = 6_000_000
Line = tuple[float, float, float, float]


@dataclass(frozen=True)
class CadAssemblyProjection:
    views: tuple[tuple[Line, ...], ...]


def parse_projection(data: Any) -> CadAssemblyProjection:
    if not isinstance(data, dict) or set(data) != set(PLANES):
        raise CadPreviewError('output')
    total = 0
    views: list[tuple[Line, ...]] = []
    for plane in PLANES:
        source = data[plane]
        if not isinstance(source, list) or not source:
            raise CadPreviewError('output')
        total += len(source)
        if total > MAX_SEGMENTS:
            raise CadPreviewError('output')
        lines: list[Line] = []
        for line in source:
            if (not isinstance(line, list) or len(line) != 4 or
                    any(type(x) not in (float, int) for x in line)):
                raise CadPreviewError('output')
            try:
                if not all(math.isfinite(x) and abs(x) <= MAX_COORDINATE for x in line):
                    raise CadPreviewError('output')
                lines.append((float(line[0]), float(line[1]), float(line[2]), float(line[3])))
            except OverflowError as error:
                raise CadPreviewError('output') from error
        views.append(tuple(lines))
    return CadAssemblyProjection(tuple(views))


class CadAssemblyProjectionJob:
    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                with suppress(OSError):
                    self._process.kill()

    def run(self, document: dict[str, Any], *, timeout: float = 90) -> CadAssemblyProjection:
        if self._cancelled.is_set():
            raise CadPreviewError('cancelled')
        with tempfile.TemporaryDirectory(prefix='suspension-projection-') as directory:
            path = Path(directory)
            source, output, report = path / 'snapshot.kima', path / 'projection.json', path / 'report.json'
            write_document(source, 'assembly', document, overwrite=False)
            args = [str(source), str(output), str(report)]
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--assembly-projection-worker', *args]
            else:
                command = [sys.executable, '-m', 'suspensionlab.core.cad_assembly_projection_worker', *args]
            try:
                flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, creationflags=flags)
            except OSError as error:
                raise CadPreviewError('start') from error
            with self._lock:
                self._process = process
                if self._cancelled.is_set():
                    with suppress(OSError):
                        process.kill()
            try:
                try:
                    code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired as error:
                    with suppress(OSError):
                        process.kill()
                    process.wait()
                    raise CadPreviewError('timeout') from error
            finally:
                with self._lock:
                    self._process = None
            if self._cancelled.is_set():
                raise CadPreviewError('cancelled')
            try:
                if not report.is_file() or report.stat().st_size > 4096:
                    raise CadPreviewError('crash')
                state = json.loads(report.read_text(encoding='utf-8'))
                if not isinstance(state, dict):
                    raise CadPreviewError('output')
                if code != 0 or state.get('status') != 'ok':
                    known = {'missing_cad', 'no_shape', 'projection', 'coordinates', 'limit', 'unexpected'}
                    reason = state.get('code')
                    raise CadPreviewError(reason if isinstance(reason, str) and reason in known else 'crash')
                if not output.is_file() or output.stat().st_size > MAX_OUTPUT_BYTES:
                    raise CadPreviewError('output')
                return parse_projection(json.loads(output.read_text(encoding='utf-8')))
            except CadPreviewError:
                raise
            except (OSError, ValueError, TypeError, MemoryError) as error:
                raise CadPreviewError('output') from error
