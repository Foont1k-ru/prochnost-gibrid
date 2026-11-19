"""Изолированный процесс и недоверенный протокол предпросмотра нескольких резов."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..model.kim_format import write_document
from .cad_assembly_projection_job import MAX_OUTPUT_BYTES, CadAssemblyProjection, parse_projection
from .cad_transport import CadPreviewError
from .cad_tube_notch import TubeNotchError
from .cad_tube_notch_sequence import (
    MAX_CUTS,
    MAX_SEQUENCE_BYTES,
    MAX_SEQUENCE_SEGMENTS,
    TubeNotchSequenceError,
    validate_notch_sequence,
)


@dataclass(frozen=True, slots=True)
class SequenceStagePreview:
    cutter_id: str
    projection: CadAssemblyProjection
    pair_before: CadAssemblyProjection
    pair_after: CadAssemblyProjection


@dataclass(frozen=True, slots=True)
class SequencePreview:
    before: CadAssemblyProjection
    stages: tuple[SequenceStagePreview, ...]

    @property
    def after(self) -> CadAssemblyProjection:
        return self.stages[-1].projection


class SequencePreviewError(CadPreviewError):
    def __init__(self, code: str, step_index: int, cutter_id: str) -> None:
        super().__init__(code)
        self.step_index, self.cutter_id = step_index, cutter_id


def parse_sequence_preview(value: Any, order: tuple[str, ...]) -> SequencePreview:
    if (not isinstance(value, dict) or set(value) != {'before', 'stages'} or
            not 1 <= len(order) <= MAX_CUTS or not isinstance(value['stages'], list) or
            len(value['stages']) != len(order)):
        raise CadPreviewError('output')
    before = parse_projection(value['before'])
    total_segments = sum(len(lines) for lines in before.views)
    stages: list[SequenceStagePreview] = []
    for item, cutter in zip(value['stages'], order, strict=True):
        if (not isinstance(item, dict) or set(item) != {'cutter', 'projection', 'pair_before', 'pair_after'} or
                item['cutter'] != cutter):
            raise CadPreviewError('output')
        projection = parse_projection(item['projection'])
        pair_before, pair_after = parse_projection(item['pair_before']), parse_projection(item['pair_after'])
        total_segments += sum(len(lines) for part in (projection, pair_before, pair_after) for lines in part.views)
        if (total_segments > MAX_SEQUENCE_SEGMENTS or projection.bounds_mm != before.bounds_mm or
                pair_before.bounds_mm != pair_after.bounds_mm):
            raise CadPreviewError('output')
        stages.append(SequenceStagePreview(cutter, projection, pair_before, pair_after))
    return SequencePreview(before, tuple(stages))


class SequencePreviewJob:
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

    def run(self, document: dict[str, Any], tube: str, cutters: list[str] | tuple[str, ...], *,
            timeout: float = 240) -> SequencePreview:
        if self._cancelled.is_set():
            raise CadPreviewError('cancelled')
        snapshot = deepcopy(document)
        try:
            order = validate_notch_sequence(snapshot, tube, cutters)
        except TubeNotchSequenceError as error:
            raise SequencePreviewError(error.code, error.step_index, error.cutter_id) from error
        except TubeNotchError as error:
            raise CadPreviewError(error.code) from error
        with tempfile.TemporaryDirectory(prefix='suspension-notch-sequence-') as directory:
            path = Path(directory)
            source, output, report = path / 'snapshot.kima', path / 'preview.json', path / 'report.json'
            write_document(source, 'assembly', snapshot, overwrite=False)
            args = [str(source), str(output), str(report), tube, *order]
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--tube-notch-sequence-worker', *args]
            else:
                command = [sys.executable, '-m', 'suspensionlab.core.cad_tube_notch_sequence_worker', *args]
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
                if code != 0:
                    known = {'missing_cad', 'no_shape', 'projection', 'coordinates', 'limit', 'unexpected',
                             'no_overlap', 'empty_or_split', 'invalid_result', 'invalid_tube', 'invalid_volume',
                             'intersection_failed', 'cut_failed', 'unsupported_pair', 'missing_plate',
                             'invalid_cutter', 'same_tube', 'duplicate_cutter', 'invalid_sequence'}
                    reason = state.get('code')
                    if state.get('status') != 'error' or not isinstance(reason, str) or reason not in known:
                        raise CadPreviewError('crash')
                    if set(state) == {'status', 'code', 'step', 'cutter'}:
                        index, cutter = state['step'], state['cutter']
                        if type(index) is not int or not 0 <= index < len(order) or cutter != order[index]:
                            raise CadPreviewError('output')
                        raise SequencePreviewError(reason, index, cutter)
                    if set(state) != {'status', 'code'}:
                        raise CadPreviewError('output')
                    raise CadPreviewError(reason)
                if state != {'status': 'ok'}:
                    raise CadPreviewError('output')
                max_bytes = min(MAX_SEQUENCE_BYTES, (1 + 3 * len(order)) * MAX_OUTPUT_BYTES)
                if not output.is_file() or output.stat().st_size > max_bytes:
                    raise CadPreviewError('output')
                return parse_sequence_preview(json.loads(output.read_text(encoding='utf-8')), order)
            except CadPreviewError:
                raise
            except (OSError, ValueError, TypeError, MemoryError) as error:
                raise CadPreviewError('output') from error
