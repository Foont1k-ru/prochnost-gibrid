"""Два реза оцениваются вместе, без изменения исходного документа."""
from copy import deepcopy
from itertools import combinations

import pytest
from test_fixed_arm_housings import housings
from test_fixed_arm_suggestions import document

from suspensionlab.core import fixed_arm_plans as plans
from suspensionlab.core.cad_fixed_arm_overlap_job import FixedArmOverlapJob, OverlapJobError, _parse_plan
from suspensionlab.model.fixed_arm_housings import make_housing_preview


def fixture():
    return make_housing_preview(document(), housings())


def request(doc):
    return {'document': doc, 'requirements': {'tube_front|tube_rear': 0, 'tube_front|housing_front': .5}}


def measurements(candidate):
    names = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    joint = candidate.get('tube_joint')
    notch = (candidate.get('notches') or {}).get('front')
    values = []
    for index, (left, right) in enumerate(combinations(names, 2)):
        distance, overlap = 3., 0.
        if index == 0 and joint is None:
            distance, overlap = 0., 1.
        if index == 1 and (notch is None or notch < 1):
            distance, overlap = 0., 1.
        values.append({'left': left, 'right': right, 'distance_mm': distance,
                       'overlap_mm3': overlap, 'threshold_mm3': 1e-6})
    return values


def test_two_cut_plan_requires_both_checked_and_is_detached(monkeypatch):
    doc = fixture()
    before = deepcopy(doc)
    monkeypatch.setattr(plans, 'measure_proximity', measurements)
    result = plans.suggest_plan(request(doc))
    assert result['outcome'] == 'candidate' and len(result['actions']) == 2
    assert {a['pair'] for a in result['actions']} == set(request(doc)['requirements'])
    assert {a['kind'] for a in result['actions']} == {'joint', 'housing'}
    parsed = _parse_plan({'status': 'ok', **result}, request(doc))
    assert parsed.after is not None and all(p.status == 'gap' for p in parsed.after.pairs)
    assert doc == before
    forged = deepcopy(result)
    forged['after'][0]['overlap_mm3'] = 1
    forged['after'][0]['distance_mm'] = 0
    with pytest.raises(OverlapJobError):
        _parse_plan({'status': 'ok', **forged}, request(doc))
    for mutate in (lambda a: a[1].update(pair=a[0]['pair']),
                   lambda a: a[0].update(radial_clearance_mm=42),
                   lambda a: a[0].update(radial_clearance_mm=True),
                   lambda a: a[0].update(radial_clearance_mm=float('nan')),
                   lambda a: a[0].update(radial_clearance_mm=10**400),
                   lambda a: a[0].update(kind='unsupported'),
                   lambda a: a.append(a[0])):
        forged = deepcopy(result)
        mutate(forged['actions'])
        with pytest.raises(OverlapJobError):
            _parse_plan({'status': 'ok', **forged}, request(doc))


def test_unsupported_unmet_and_missing_requirements_never_guessed(monkeypatch):
    doc = fixture()
    monkeypatch.setattr(plans, 'measure_proximity', measurements)
    assert plans.suggest_plan({'document': doc, 'requirements': {}})['outcome'] == 'insufficient'
    assert plans.suggest_plan({'document': doc, 'requirements': {'tube_front|tube_rear': 0}})['outcome'] == 'insufficient'
    assert plans.suggest_plan({'document': doc, 'requirements': {'tube_front|tube_rear': 0,
                            'tube_front|housing_rear': 4}})['outcome'] == 'insufficient'


def test_other_requirements_and_ambiguous_geometry_block_plans(monkeypatch):
    doc = fixture()
    def gets_worse(candidate):
        values = measurements(candidate)
        if candidate != doc:
            values[-1]['distance_mm'] = 1  # existing fulfilled 2 mm requirement is violated
        return values
    monkeypatch.setattr(plans, 'measure_proximity', gets_worse)
    req = request(doc)
    req['requirements']['housing_front|housing_rear'] = 2
    outcome = plans.suggest_plan(req)
    assert outcome['outcome'] == 'no_candidate'
    def ambiguous(candidate):
        values = measurements(candidate)
        values[-1].update(overlap_mm3=1e-7, distance_mm=0)
        return values
    monkeypatch.setattr(plans, 'measure_proximity', ambiguous)
    assert plans.suggest_plan(req)['outcome'] == 'unverified'


def test_candidate_error_makes_failed_search_unverified(monkeypatch):
    doc = fixture()
    def measure(candidate):
        if candidate != doc:
            raise RuntimeError('CAD error')
        return measurements(candidate)
    monkeypatch.setattr(plans, 'measure_proximity', measure)
    assert plans.suggest_plan(request(doc))['outcome'] == 'unverified'


def test_real_subprocess_checks_two_cuts_and_all_pairs():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    h = housings()
    h['front']['axis'] = [1, 0, 0]
    h['front']['length_mm'] = 40
    doc = make_housing_preview(document(), h)
    original = deepcopy(doc)
    result = FixedArmOverlapJob().run_plan(doc, request(doc)['requirements'], timeout=120)
    assert result.outcome == 'candidate' and len(result.actions) == 2
    assert result.after is not None and len(result.after.pairs) == 6
    assert result.after.pairs[0].overlap_mm3 == 0 and result.after.pairs[1].distance_mm >= .50001
    assert result.after.pairs[4].status == 'intersection'  # other existing problems are not hidden
    assert doc == original


def test_combination_can_recover_constraint_that_blocks_individual_cut(monkeypatch):
    from suspensionlab.core import fixed_arm_suggestions as single

    doc = fixture()
    def measured(candidate):
        values = measurements(candidate)
        if candidate.get('tube_joint') and not candidate.get('notches'):
            values[-1]['distance_mm'] = 1
        return values
    monkeypatch.setattr(plans, 'measure_proximity', measured)
    monkeypatch.setattr(single, 'measure_proximity', measured)
    req = request(doc)
    req['requirements']['housing_front|housing_rear'] = 2
    single_result = single.suggest({'document': doc, 'left': 'tube_front', 'right': 'tube_rear',
                                    'minimum_mm': 0, 'requirements': req['requirements']})
    assert single_result['outcome'] == 'no_candidate' and 'other_requirement' in single_result['reasons']
    outcome = plans.suggest_plan(req)
    assert outcome['outcome'] == 'candidate'
    parsed = _parse_plan({'status': 'ok', **outcome}, req)
    assert parsed.after is not None and parsed.after.pairs[-1].distance_mm == 3


def test_plan_budget_covers_different_problem_pairs(monkeypatch):
    doc = fixture()
    def all_bad(candidate):
        values = measurements(candidate)
        values[4].update(distance_mm=0, overlap_mm3=1)
        return values
    monkeypatch.setattr(plans, 'measure_proximity', all_bad)
    req = {'tube_front|tube_rear': 0, 'tube_front|housing_front': .5, 'tube_rear|housing_rear': .5}
    baseline = plans._parse_proximity(all_bad(doc), doc)
    options = plans.plan_options(doc, req, baseline)
    assert len(options) == plans.MAX_PLANS
    assert {frozenset((a[0], b[0])) for a, b in options} == {
        frozenset(('tube_front|tube_rear', 'tube_front|housing_front')),
        frozenset(('tube_front|tube_rear', 'tube_rear|housing_rear')),
        frozenset(('tube_front|housing_front', 'tube_rear|housing_rear')),
    }
