"""Ограниченный подбор двух разных резов на одном исходном CAD-снимке."""
from __future__ import annotations

from itertools import combinations, product
from typing import Any

from ..model.fixed_arm_clearances import validate_requirements
from ..model.fixed_arm_housings import PREVIEW_FORMAT, validate_housing_preview
from ..model.welded_arm import weldment_source_matches
from .cad_fixed_arm_overlap import measure_proximity
from .cad_fixed_arm_overlap_job import ProximityResult, _parse_proximity
from .fixed_arm_suggestions import _requirements_not_worse, candidate_document, candidate_options, satisfies

# Перебор намеренно ограничен: результат не является глобальным оптимумом.
MAX_OPTIONS_PER_PAIR = 4
MAX_PLANS = 18
Action = tuple[str, str, str, float]  # пара, тип, ветвь, радиальный размер
Plan = tuple[Action, Action]


def validate_plan_request(value: Any) -> tuple[dict[str, Any], dict[str, float]]:
    if not isinstance(value, dict) or set(value) != {'document', 'requirements'}:
        raise ValueError('invalid_request')
    document = value['document']
    if not isinstance(document, dict):
        raise ValueError('invalid_document')
    if document.get('format') == PREVIEW_FORMAT:
        validate_housing_preview(document)
    elif not weldment_source_matches(document):
        raise ValueError('invalid_document')
    housings = document.get('format') == PREVIEW_FORMAT and document.get('housings') is not None
    return document, validate_requirements(value['requirements'], housings=housings)


def plan_options(document: dict[str, Any], requirements: dict[str, float], baseline: ProximityResult) -> list[Plan]:
    """По четыре первых варианта на пару, до 18 комбинаций с чередованием пар."""
    groups: list[list[Action]] = []
    for pair in baseline.pairs:
        key = f'{pair.left}|{pair.right}'
        minimum = requirements.get(key)
        if minimum is None or satisfies(pair, minimum):
            continue
        options, _ = candidate_options(document, pair.left, pair.right, minimum)
        if options:
            groups.append([(key, kind, target, clearance)
                           for kind, target, clearance in options[:MAX_OPTIONS_PER_PAIR]])
    buckets: list[list[Plan]] = []
    for left, right in combinations(groups, 2):
        plans: list[Plan] = []
        for a, b in product(left, right):
            # Нельзя использовать два реза по другой трубе или менять один и тот же параметр дважды.
            if (a[1] == b[1] == 'joint') or (a[1], a[2]) == (b[1], b[2]):
                continue
            plans.append((a, b))
        if plans:
            buckets.append(plans)
    result: list[Plan] = []
    for index in range(MAX_OPTIONS_PER_PAIR ** 2):
        for bucket in buckets:
            if index < len(bucket):
                result.append(bucket[index])
                if len(result) == MAX_PLANS:
                    return result
    return result


def plan_document(document: dict[str, Any], plan: Plan) -> dict[str, Any]:
    candidate = document
    for _, kind, target, clearance in plan:
        candidate = candidate_document(candidate, kind, target, clearance)
    return candidate


def acceptable_plan(baseline: ProximityResult, after: ProximityResult,
                    requirements: dict[str, float], plan: Plan) -> bool:
    targets = {action[0] for action in plan}
    if len(targets) != 2 or not targets.issubset(requirements):
        return False
    if any(p.status in ('error', 'uncertain_overlap') for p in (*baseline.pairs, *after.pairs)):
        return False
    if len(baseline.pairs) != len(after.pairs):
        return False
    seen = set()
    for before, result in zip(baseline.pairs, after.pairs, strict=True):
        if (before.left, before.right) != (result.left, result.right):
            return False
        key = f'{before.left}|{before.right}'
        if key in targets:
            if satisfies(before, requirements[key]) or not satisfies(result, requirements[key]):
                return False
            seen.add(key)
        elif not _requirements_not_worse(before, result, requirements.get(key)):
            return False
    return seen == targets


def suggest_plan(value: Any) -> dict[str, Any]:
    document, requirements = validate_plan_request(value)
    initial_rows = measure_proximity(document)
    baseline = _parse_proximity(initial_rows, document)
    if any(p.status in ('error', 'uncertain_overlap') for p in baseline.pairs):
        return {'outcome': 'unverified', 'baseline': initial_rows}
    plans = plan_options(document, requirements, baseline)
    if not plans:
        return {'outcome': 'insufficient', 'baseline': initial_rows}
    unverified = False
    for plan in plans:
        try:
            candidate = plan_document(document, plan)
            rows = measure_proximity(candidate)
            after = _parse_proximity(rows, candidate)
            if any(p.status in ('error', 'uncertain_overlap') for p in after.pairs):
                unverified = True
                continue
            if acceptable_plan(baseline, after, requirements, plan):
                actions = [{'pair': pair, 'kind': kind, 'target': target, 'radial_clearance_mm': clearance}
                           for pair, kind, target, clearance in plan]
                return {'outcome': 'candidate', 'baseline': initial_rows, 'actions': actions, 'after': rows}
        except Exception:
            unverified = True
    return {'outcome': 'unverified' if unverified else 'no_candidate', 'baseline': initial_rows}
