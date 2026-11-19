"""Запуск и проверка результата изолированного просмотра подрезки трубы."""
from __future__ import annotations

import json
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
from .cad_assembly_projection_job import MAX_OUTPUT_BYTES, CadAssemblyProjection, parse_projection
from .cad_transport import CadPreviewError


@dataclass(frozen=True)
class TubeNotchPreview:
    before: CadAssemblyProjection
    after: CadAssemblyProjection


def parse_notch_preview(value: Any) -> TubeNotchPreview:
    if not isinstance(value, dict) or set(value) != {'before', 'after'}:
        raise CadPreviewError('output')
    before, after = parse_projection(value['before']), parse_projection(value['after'])
    if before.bounds_mm != after.bounds_mm:
        raise CadPreviewError('output')
    return TubeNotchPreview(before, after)


class TubeNotchPreviewJob:
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

    def run(self, document: dict[str, Any], tube: str, housing: str, *, timeout: float = 90) -> TubeNotchPreview:
        if self._cancelled.is_set():
            raise CadPreviewError('cancelled')
        if tube not in ('tube_front', 'tube_rear') or housing not in ('housing_front', 'housing_rear', 'ball_plate'):
            raise CadPreviewError('unsupported_pair')
        with tempfile.TemporaryDirectory(prefix='suspension-notch-') as directory:
            path = Path(directory)
            source, output, report = path / 'snapshot.kima', path / 'preview.json', path / 'report.json'
            write_document(source, 'assembly', document, overwrite=False)
            args = [str(source), str(output), str(report), tube, housing]
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--tube-notch-worker', *args]
            else:
                command = [sys.executable, '-m', 'suspensionlab.core.cad_tube_notch_worker', *args]
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
                    known = {'missing_cad', 'no_shape', 'projection', 'coordinates', 'limit', 'unexpected',
                             'no_overlap', 'empty_or_split', 'invalid_result', 'invalid_tube', 'invalid_volume',
                             'intersection_failed', 'cut_failed', 'unsupported_pair', 'missing_plate',
                             'invalid_cutter'}
                    reason = state.get('code')
                    raise CadPreviewError(reason if isinstance(reason, str) and reason in known else 'crash')
                if not output.is_file() or output.stat().st_size > 2 * MAX_OUTPUT_BYTES:
                    raise CadPreviewError('output')
                return parse_notch_preview(json.loads(output.read_text(encoding='utf-8')))
            except CadPreviewError:
                raise
            except (OSError, ValueError, TypeError, MemoryError) as error:
                raise CadPreviewError('output') from error
