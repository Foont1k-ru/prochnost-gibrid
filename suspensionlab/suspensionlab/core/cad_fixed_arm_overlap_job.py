"""Изолированный проверяемый процесс анализа пересечения труб."""
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

from ..model.fixed_arm_housings import PREVIEW_FORMAT, validate_housing_preview
from ..model.project_limits import MAX_PROJECT_BYTES
from ..model.welded_arm import weldment_source_matches


class OverlapJobError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class OverlapResult:
    overlap_mm3: float
    threshold_mm3: float


class FixedArmOverlapJob:
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

    def run(self, document: dict[str, Any], *, timeout: float = 90) -> OverlapResult:
        if self._cancelled.is_set():
            raise OverlapJobError('cancelled')
        try:
            if document.get('format') == PREVIEW_FORMAT:
                validate_housing_preview(document)
            elif not weldment_source_matches(document):
                raise ValueError('source')
            content = json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(content) > MAX_PROJECT_BYTES:
                raise ValueError('size')
        except (TypeError, ValueError, KeyError, RecursionError, OverflowError) as error:
            raise OverlapJobError('invalid') from error
        with tempfile.TemporaryDirectory(prefix='suspension-fixed-overlap-') as directory:
            source, target = Path(directory) / 'snapshot.json', Path(directory) / 'result.json'
            source.write_bytes(content)
            args = [str(source), str(target)]
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--fixed-arm-overlap-worker', *args]
            else:
                command = [sys.executable, '-m', 'suspensionlab.core.cad_fixed_arm_overlap', *args]
            try:
                flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, creationflags=flags)
            except OSError as error:
                raise OverlapJobError('start') from error
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
                    raise OverlapJobError('timeout') from error
            finally:
                with self._lock:
                    self._process = None
            if self._cancelled.is_set():
                raise OverlapJobError('cancelled')
            try:
                if code != 0 or not target.is_file() or target.stat().st_size > 4096:
                    raise OverlapJobError('failed')
                result = json.loads(target.read_text(encoding='utf-8'))
                if not isinstance(result, dict) or set(result) != {'status', 'overlap_mm3', 'threshold_mm3'} or result['status'] != 'ok':
                    raise OverlapJobError('output')
                numbers = [result['overlap_mm3'], result['threshold_mm3']]
                if any(type(n) not in (int, float) or not math.isfinite(n) or n < 0 or n > 1e24 for n in numbers) or numbers[1] <= 0:
                    raise OverlapJobError('output')
                return OverlapResult(float(numbers[0]), float(numbers[1]))
            except (OSError, UnicodeError, ValueError, OverflowError, TypeError) as error:
                raise OverlapJobError('output') from error
