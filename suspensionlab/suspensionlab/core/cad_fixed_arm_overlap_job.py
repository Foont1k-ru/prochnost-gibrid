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
from itertools import combinations
from pathlib import Path
from typing import Any

from ..model.fixed_arm_clearances import DISTANCE_TOLERANCE_MM
from ..model.fixed_arm_housings import PREVIEW_FORMAT, validate_housing_preview
from ..model.project_limits import MAX_PROJECT_BYTES
from ..model.welded_arm import weldment_source_matches


class OverlapJobError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class OverlapResult:
    overlap_mm3: float
    threshold_mm3: float


@dataclass(frozen=True, slots=True)
class PairOverlap:
    left: str
    right: str
    overlap_mm3: float
    threshold_mm3: float


@dataclass(frozen=True, slots=True)
class PairwiseResult:
    pairs: tuple[PairOverlap, ...]


@dataclass(frozen=True, slots=True)
class PairProximity:
    left: str
    right: str
    overlap_mm3: float | None
    threshold_mm3: float | None
    distance_mm: float | None
    points: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None
    solutions: int | None = None

    @property
    def status(self) -> str:
        if self.overlap_mm3 is None or self.threshold_mm3 is None or self.distance_mm is None:
            return 'error'
        if self.overlap_mm3 > self.threshold_mm3:
            return 'intersection'
        if self.overlap_mm3 > 0:
            return 'uncertain_overlap'
        if self.distance_mm <= DISTANCE_TOLERANCE_MM:
            return 'near'
        return 'gap'


@dataclass(frozen=True, slots=True)
class ProximityResult:
    pairs: tuple[PairProximity, ...]


@dataclass(frozen=True, slots=True)
class SuggestionResult:
    outcome: str
    baseline: ProximityResult
    kind: str | None = None
    target: str | None = None
    radial_clearance_mm: float | None = None
    after: ProximityResult | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AutoPairResult:
    left: str
    right: str
    outcome: str
    suggestion: SuggestionResult | None = None


@dataclass(frozen=True, slots=True)
class AutoSuggestionResult:
    baseline: ProximityResult
    pairs: tuple[AutoPairResult, ...]


def _read_numbers(item: dict[str, Any]) -> tuple[float, float]:
    numbers = [item['overlap_mm3'], item['threshold_mm3']]
    try:
        if (any(type(n) not in (int, float) or not math.isfinite(n) or n < 0 or n > 1e24 for n in numbers) or
                numbers[1] <= 0):
            raise OverlapJobError('output')
        return float(numbers[0]), float(numbers[1])
    except (TypeError, ValueError, OverflowError) as error:
        raise OverlapJobError('output') from error


def _expected_pairs(document: dict[str, Any]) -> list[tuple[str, str]]:
    names: tuple[str, ...] = ('tube_front', 'tube_rear')
    if document.get('format') == PREVIEW_FORMAT and document.get('housings') is not None:
        names += ('housing_front', 'housing_rear')
    return list(combinations(names, 2))


def _parse_all_pairs(value: Any, document: dict[str, Any]) -> PairwiseResult:
    if not isinstance(value, list):
        raise OverlapJobError('output')
    expected = _expected_pairs(document)
    if len(value) != len(expected):
        raise OverlapJobError('output')
    result = []
    for item, (left, right) in zip(value, expected, strict=True):
        if (not isinstance(item, dict) or set(item) != {'left', 'right', 'overlap_mm3', 'threshold_mm3'} or
                item['left'] != left or item['right'] != right):
            raise OverlapJobError('output')
        overlap, threshold = _read_numbers(item)
        result.append(PairOverlap(left, right, overlap, threshold))
    return PairwiseResult(tuple(result))


def _parse_proximity(value: Any, document: dict[str, Any]) -> ProximityResult:
    expected = _expected_pairs(document)
    if not isinstance(value, list) or len(value) != len(expected):
        raise OverlapJobError('output')
    result = []
    for item, (left, right) in zip(value, expected, strict=True):
        if not isinstance(item, dict) or item.get('left') != left or item.get('right') != right:
            raise OverlapJobError('output')
        if set(item) == {'left', 'right', 'error'} and item['error'] == 'measurement_failed':
            result.append(PairProximity(left, right, None, None, None))
            continue
        base_keys = {'left', 'right', 'overlap_mm3', 'threshold_mm3', 'distance_mm'}
        if set(item) not in (base_keys, base_keys | {'points', 'solutions'}):
            raise OverlapJobError('output')
        overlap, threshold = _read_numbers(item)
        distance = item['distance_mm']
        try:
            if type(distance) not in (int, float) or not math.isfinite(distance) or not 0 <= distance <= 1e12:
                raise OverlapJobError('output')
            points = None
            solutions = None
            if 'points' in item:
                values = item['points']
                solutions = item['solutions']
                if (overlap != 0 or distance <= DISTANCE_TOLERANCE_MM or type(solutions) is not int or
                        not 1 <= solutions <= 1000000 or not isinstance(values, list) or len(values) != 2 or
                        any(not isinstance(p, list) or len(p) != 3 for p in values)):
                    raise OverlapJobError('output')
                if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e10 for p in values for v in p):
                    raise OverlapJobError('output')
                points = ((float(values[0][0]), float(values[0][1]), float(values[0][2])),
                          (float(values[1][0]), float(values[1][1]), float(values[1][2])))
                if abs(math.dist(points[0], points[1]) - distance) > max(1e-5, distance * 1e-8):
                    raise OverlapJobError('output')
            result.append(PairProximity(left, right, overlap, threshold, float(distance), points, solutions))
        except (TypeError, ValueError, OverflowError) as error:
            raise OverlapJobError('output') from error
    return ProximityResult(tuple(result))


def _parse_suggestion(result: Any, request: dict[str, Any]) -> SuggestionResult:
    from .fixed_arm_suggestions import (
        _requirements_not_worse,
        candidate_document,
        candidate_options,
        satisfies,
        validate_request,
    )

    doc, left, right, minimum = validate_request(request)
    if not isinstance(result, dict) or result.get('outcome') not in ('candidate', 'already', 'unverified', 'no_candidate'):
        raise OverlapJobError('output')
    outcome = result['outcome']
    keys = {'status', 'outcome', 'baseline'}
    if outcome == 'candidate':
        keys |= {'kind', 'target', 'radial_clearance_mm', 'after'}
    elif outcome in ('no_candidate', 'unverified') and 'reasons' in result:
        keys.add('reasons')
    if set(result) != keys:
        raise OverlapJobError('output')
    reasons = result.get('reasons', [])
    allowed_reasons = {'baseline_error', 'baseline_ambiguous', 'unsupported', 'existing_cut', 'selected_not_met',
                       'other_geometry', 'other_requirement', 'candidate_unverified', 'cad_error'}
    if (not isinstance(reasons, list) or len(reasons) > len(allowed_reasons) or
            any(not isinstance(reason, str) or reason not in allowed_reasons for reason in reasons) or
            len(set(reasons)) != len(reasons)):
        raise OverlapJobError('output')
    baseline = _parse_proximity(result['baseline'], doc)
    options, constrained = candidate_options(doc, left, right, minimum)
    supported = (left, right) in {('tube_front', 'tube_rear'), ('tube_front', 'housing_front'),
                                  ('tube_rear', 'housing_rear')}
    if (('unsupported' in reasons and supported) or ('existing_cut' in reasons and not constrained) or
            ('baseline_error' in reasons and not any(p.status == 'error' for p in baseline.pairs)) or
            ('baseline_ambiguous' in reasons and not any(p.status == 'uncertain_overlap' for p in baseline.pairs)) or
            (outcome == 'no_candidate' and any(r in reasons for r in
                                               ('baseline_error', 'baseline_ambiguous', 'candidate_unverified', 'cad_error')))):
        raise OverlapJobError('output')
    if outcome == 'already':
        selected = next((pair for pair in baseline.pairs if (pair.left, pair.right) == (left, right)), None)
        if (selected is None or not satisfies(selected, minimum) or
                any(pair.status in ('error', 'uncertain_overlap') for pair in baseline.pairs)):
            raise OverlapJobError('output')
    if outcome != 'candidate':
        return SuggestionResult(outcome, baseline, reasons=tuple(reasons))
    if any(pair.status in ('error', 'uncertain_overlap') for pair in baseline.pairs):
        raise OverlapJobError('output')
    kind, target, clearance = result['kind'], result['target'], result['radial_clearance_mm']
    allowed = {('tube_front', 'tube_rear'): {('joint', 'front'), ('joint', 'rear')},
               ('tube_front', 'housing_front'): {('housing', 'front')},
               ('tube_rear', 'housing_rear'): {('housing', 'rear')}}
    if (kind, target) not in allowed.get((left, right), set()) or type(clearance) not in (int, float):
        raise OverlapJobError('output')
    if not math.isfinite(clearance) or (kind, target, clearance) not in options:
        raise OverlapJobError('output')
    try:
        candidate = candidate_document(doc, kind, target, clearance)
        after = _parse_proximity(result['after'], candidate)
        selected = next(p for p in after.pairs if (p.left, p.right) == (left, right))
        if (not satisfies(selected, minimum) or
                not all((a.left, a.right) == (b.left, b.right) and
                        ((a.left, a.right) == (left, right) or
                         _requirements_not_worse(a, b, request.get('requirements', {}).get(f'{a.left}|{a.right}')))
                        for a, b in zip(baseline.pairs, after.pairs, strict=True))):
            raise OverlapJobError('output')
    except (ValueError, TypeError, KeyError, StopIteration, OverflowError) as error:
        raise OverlapJobError('output') from error
    return SuggestionResult(outcome, baseline, kind, target, float(clearance), after)


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
        result = self._run(document, timeout=timeout, mode='overlap')
        if not isinstance(result, OverlapResult):
            raise OverlapJobError('output')
        return result

    def run_all(self, document: dict[str, Any], *, timeout: float = 90) -> PairwiseResult:
        result = self._run(document, timeout=timeout, mode='all')
        if not isinstance(result, PairwiseResult):
            raise OverlapJobError('output')
        return result

    def run_proximity(self, document: dict[str, Any], *, timeout: float = 90) -> ProximityResult:
        result = self._run(document, timeout=timeout, mode='proximity')
        if not isinstance(result, ProximityResult):
            raise OverlapJobError('output')
        return result

    def run_suggestion(self, document: dict[str, Any], left: str, right: str, minimum_mm: float,
                       *, requirements: dict[str, float] | None = None, timeout: float = 180) -> SuggestionResult:
        request: dict[str, Any] = {'document': document, 'left': left, 'right': right, 'minimum_mm': minimum_mm}
        if requirements is not None:
            request['requirements'] = requirements
        result = self._run(document, timeout=timeout, mode='suggest', request=request)
        if not isinstance(result, SuggestionResult):
            raise OverlapJobError('output')
        return result

    def run_auto(self, document: dict[str, Any], requirements: dict[str, float]) -> AutoSuggestionResult:
        """Проверяет все пары; кандидаты независимы и не изменяют исходный снимок."""
        from ..model.fixed_arm_clearances import validate_requirements
        from .fixed_arm_suggestions import satisfies

        housings = document.get('format') == PREVIEW_FORMAT and document.get('housings') is not None
        requirements = validate_requirements(requirements, housings=housings)
        baseline = self.run_proximity(document)
        blocked = any(p.status in ('error', 'uncertain_overlap') for p in baseline.pairs)
        supported = {('tube_front', 'tube_rear'), ('tube_front', 'housing_front'),
                     ('tube_rear', 'housing_rear')}
        results = []
        for pair in baseline.pairs:
            if self._cancelled.is_set():
                raise OverlapJobError('cancelled')
            minimum = requirements.get(f'{pair.left}|{pair.right}')
            proposal = None
            if pair.status in ('error', 'uncertain_overlap'):
                outcome = 'unverified'
            elif minimum is None:
                outcome = 'requirement_missing' if pair.status == 'intersection' else 'no_requirement'
            elif satisfies(pair, minimum):
                outcome = 'satisfied'
            elif blocked:
                outcome = 'unverified'
            elif (pair.left, pair.right) not in supported:
                outcome = 'unsupported'
            else:
                try:
                    proposal = self.run_suggestion(document, pair.left, pair.right, minimum,
                                                   requirements=requirements)
                    outcome = proposal.outcome
                except OverlapJobError:
                    if self._cancelled.is_set():
                        raise OverlapJobError('cancelled') from None
                    outcome = 'failed'
            results.append(AutoPairResult(pair.left, pair.right, outcome, proposal))
        return AutoSuggestionResult(baseline, tuple(results))

    def _run(self, document: dict[str, Any], *, timeout: float, mode: str,
             request: dict[str, Any] | None = None) -> OverlapResult | PairwiseResult | ProximityResult | SuggestionResult:
        if self._cancelled.is_set():
            raise OverlapJobError('cancelled')
        try:
            if document.get('format') == PREVIEW_FORMAT:
                validate_housing_preview(document)
            elif not weldment_source_matches(document):
                raise ValueError('source')
            if mode == 'suggest':
                from .fixed_arm_suggestions import validate_request
                validate_request(request)
            content = json.dumps(request if mode == 'suggest' else document,
                                 ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(content) > MAX_PROJECT_BYTES:
                raise ValueError('size')
            snapshot = json.loads(content)
        except (TypeError, ValueError, KeyError, RecursionError, OverflowError) as error:
            raise OverlapJobError('invalid') from error
        with tempfile.TemporaryDirectory(prefix='suspension-fixed-overlap-') as directory:
            source, target = Path(directory) / 'snapshot.json', Path(directory) / 'result.json'
            source.write_bytes(content)
            args = [str(source), str(target)]
            if mode != 'overlap':
                args.append(mode)
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
                if code != 0 or not target.is_file() or target.stat().st_size > 16384:
                    raise OverlapJobError('failed')
                from ..model.project_io import _unique_object

                result = json.loads(target.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
                if not isinstance(result, dict) or result.get('status') != 'ok':
                    raise OverlapJobError('output')
                if mode == 'suggest':
                    return _parse_suggestion(result, snapshot)
                if mode in ('all', 'proximity'):
                    if set(result) != {'status', 'pairs'}:
                        raise OverlapJobError('output')
                    return (_parse_all_pairs(result['pairs'], snapshot) if mode == 'all' else
                            _parse_proximity(result['pairs'], snapshot))
                if set(result) != {'status', 'overlap_mm3', 'threshold_mm3'}:
                    raise OverlapJobError('output')
                overlap, threshold = _read_numbers(result)
                return OverlapResult(overlap, threshold)
            except (OSError, UnicodeError, ValueError, OverflowError, TypeError) as error:
                raise OverlapJobError('output') from error
