"""Ограниченный перебор допустимых резов без изменения исходного документа."""
from __future__ import annotations

import math
from typing import Any

from ..model.fixed_arm_clearances import validate_requirements
from ..model.fixed_arm_housings import PREVIEW_FORMAT, make_housing_preview, validate_housing_preview
from ..model.welded_arm import weldment_source_matches
from .cad_fixed_arm_overlap import measure_proximity
from .cad_fixed_arm_overlap_job import DISTANCE_TOLERANCE_MM, PairProximity, _parse_proximity


def validate_request(value: Any) -> tuple[dict[str, Any], str, str, float]:
    if not isinstance(value, dict) or set(value) not in (
            {'document', 'left', 'right', 'minimum_mm'},
            {'document', 'left', 'right', 'minimum_mm', 'requirements'}):
        raise ValueError('invalid_request')
    doc, left, right, minimum = (value[k] for k in ('document', 'left', 'right', 'minimum_mm'))
    if not isinstance(doc, dict):
        raise ValueError('invalid_document')
    if doc.get('format') == PREVIEW_FORMAT:
        validate_housing_preview(doc)
    elif not weldment_source_matches(doc):
        raise ValueError('invalid_document')
    if (type(minimum) not in (int, float) or not math.isfinite(minimum) or
            not (minimum == 0 or DISTANCE_TOLERANCE_MM < minimum <= 100)):
        raise ValueError('invalid_minimum')
    names: tuple[str, ...] = ('tube_front', 'tube_rear')
    if doc.get('format') == PREVIEW_FORMAT and doc.get('housings') is not None:
        names += ('housing_front', 'housing_rear')
    if left not in names or right not in names or names.index(left) >= names.index(right):
        raise ValueError('invalid_pair')
    if 'requirements' in value:
        requirements = validate_requirements(value['requirements'], housings=len(names) == 4)
        if requirements.get(f'{left}|{right}') != float(minimum):
            raise ValueError('minimum_mismatch')
    return doc, left, right, float(minimum)


def candidate_document(doc: dict[str, Any], kind: str, target: str, clearance: float) -> dict[str, Any]:
    """Строит только поддержанный рез, не меняя другие параметры."""
    if doc.get('format') == PREVIEW_FORMAT:
        tubes, housings = doc['tubes'], doc['housings']
        notches, joint = dict(doc.get('notches') or {}), doc.get('tube_joint')
    else:
        tubes, housings, notches, joint = doc, None, {}, None
    if kind == 'joint':
        if joint is not None and joint['target'] != target:
            raise ValueError('existing_joint')
        if joint is not None and clearance < joint['radial_clearance_mm']:
            raise ValueError('reduce_cut')
        joint = {'target': target, 'radial_clearance_mm': clearance}
    elif kind == 'housing':
        if housings is None or clearance < notches.get(target, 0):
            raise ValueError('invalid_cut')
        notches[target] = clearance
    else:
        raise ValueError('invalid_cut')
    return make_housing_preview(tubes, housings, notches or None, joint)


def candidate_options(doc: dict[str, Any], left: str, right: str, minimum: float) -> tuple[list[tuple[str, str, float]], bool]:
    """Детерминированный конечный набор размеров реза, не норматив зазора."""
    if (left, right) == ('tube_front', 'tube_rear'):
        options = [('joint', 'front'), ('joint', 'rear')]
    elif (left, right) in (('tube_front', 'housing_front'), ('tube_rear', 'housing_rear')):
        options = [('housing', 'front' if left == 'tube_front' else 'rear')]
    else:
        return [], False
    preview = doc.get('format') == PREVIEW_FORMAT
    joint = doc.get('tube_joint') if preview else None
    notches = (doc.get('notches') or {}) if preview else {}
    candidates = []
    constrained = False
    for kind, target in options:
        if kind == 'joint' and joint is not None and joint['target'] != target:
            constrained = True
            continue
        existing = (joint['radial_clearance_mm'] if kind == 'joint' and joint is not None else
                    notches.get(target) if kind == 'housing' else None)
        base = float(existing) if existing is not None else 0.0
        values = {min(100.0, minimum * factor) for factor in (1, 2, 4)}
        values.update(min(100.0, base + step) for step in (0.5, 1.0, 2.0))
        if existing is not None:
            values = {v for v in values if v > base}
            constrained = True
        for value in sorted(values):
            candidates.append((kind, target, value))
    candidates.sort(key=lambda item: (item[2], item[1]))
    return candidates, constrained


def satisfies(pair: PairProximity, minimum: float) -> bool:
    """Нулевой минимум допускает контакт; малые объёмы остаются неопределёнными."""
    if minimum == 0:
        return pair.status in ('near', 'gap') and pair.overlap_mm3 == 0
    return (pair.status == 'gap' and pair.distance_mm is not None and
            pair.distance_mm >= minimum + DISTANCE_TOLERANCE_MM)


def _not_worse(old: PairProximity, new: PairProximity) -> bool:
    if old.status in ('error', 'uncertain_overlap') or new.status in ('error', 'uncertain_overlap'):
        return False
    if old.status != 'intersection' and new.status == 'intersection':
        return False
    if old.status == 'gap' and new.status != 'gap':
        return False
    if old.status == 'intersection' and new.status == 'intersection':
        assert old.overlap_mm3 is not None and new.overlap_mm3 is not None and old.threshold_mm3 is not None
        if new.overlap_mm3 > old.overlap_mm3 + old.threshold_mm3:
            return False
    return True


def _requirements_not_worse(old: PairProximity, new: PairProximity, minimum: float | None) -> bool:
    if not _not_worse(old, new):
        return False
    if minimum is None:
        return True
    if satisfies(old, minimum):
        return satisfies(new, minimum)
    if old.status == 'gap' and new.status == 'gap':
        assert old.distance_mm is not None and new.distance_mm is not None
        return new.distance_mm + DISTANCE_TOLERANCE_MM >= old.distance_mm
    return True


def suggest(value: Any) -> dict[str, Any]:
    """Ограниченный перебор вариантов; не оптимизация и не гарантия безопасности."""
    doc, left, right, minimum = validate_request(value)
    requirements: dict[str, float] = value.get('requirements', {})
    initial_rows = measure_proximity(doc)
    initial = _parse_proximity(initial_rows, doc)
    baseline_reasons = {('baseline_error' if p.status == 'error' else 'baseline_ambiguous')
                        for p in initial.pairs if p.status in ('error', 'uncertain_overlap')}
    if baseline_reasons:
        return {'outcome': 'unverified', 'baseline': initial_rows, 'reasons': sorted(baseline_reasons)}
    original = next(p for p in initial.pairs if (p.left, p.right) == (left, right))
    if satisfies(original, minimum):
        return {'outcome': 'already', 'baseline': initial_rows}
    options, constrained = candidate_options(doc, left, right, minimum)
    supported = (left, right) in {('tube_front', 'tube_rear'), ('tube_front', 'housing_front'),
                                  ('tube_rear', 'housing_rear')}
    reasons: set[str] = set()
    if not supported:
        reasons.add('unsupported')
    if constrained:
        reasons.add('existing_cut')
    unverified = False
    for kind, target, clearance in options:
        try:
            candidate = candidate_document(doc, kind, target, clearance)
        except ValueError:
            unverified = True
            reasons.add('candidate_unverified')
            continue
        try:
            rows = measure_proximity(candidate)
            measured = _parse_proximity(rows, candidate)
            if any(pair.status in ('error', 'uncertain_overlap') for pair in measured.pairs):
                unverified = True
                reasons.add('candidate_unverified')
                continue
            checked = next(p for p in measured.pairs if (p.left, p.right) == (left, right))
            if not satisfies(checked, minimum):
                reasons.add('selected_not_met')
                continue
            conflicts = [(a, b) for a, b in zip(initial.pairs, measured.pairs, strict=True)
                         if (a.left, a.right) != (left, right) and
                         not _requirements_not_worse(a, b, requirements.get(f'{a.left}|{a.right}'))]
            if conflicts:
                for a, b in conflicts:
                    if not _not_worse(a, b):
                        reasons.add('other_geometry')
                    else:
                        reasons.add('other_requirement')
                continue
            return {'outcome': 'candidate', 'baseline': initial_rows, 'kind': kind, 'target': target,
                    'radial_clearance_mm': clearance, 'after': rows}
        except Exception:
            # One failed CAD operation cannot make a candidate verified.
            unverified = True
            reasons.add('cad_error')
    return {'outcome': 'unverified' if unverified else 'no_candidate', 'baseline': initial_rows,
            'reasons': sorted(reasons)}
