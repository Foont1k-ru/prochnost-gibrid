"""Кандидаты только по разрешённым парам и только после пересчёта всех тел."""
from copy import deepcopy

import pytest

from suspensionlab.core import fixed_arm_suggestions as smart
from suspensionlab.core.cad_fixed_arm_overlap_job import OverlapJobError, _parse_suggestion
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, fixed_arm_tube_document
from suspensionlab.model.templates import load_template


def document():
    p = load_template('ring')
    return fixed_arm_tube_document(capture_fixed_arm(p, -20, 20), p, 10, 2)


def request(doc):
    return {'document': doc, 'left': 'tube_front', 'right': 'tube_rear', 'minimum_mm': 0.5}


def row(distance, volume=0):
    return [{'left': 'tube_front', 'right': 'tube_rear', 'distance_mm': distance,
             'overlap_mm3': volume, 'threshold_mm3': 1e-6}]


def test_generated_candidate_requires_independent_measured_gap(monkeypatch):
    doc = document()
    before = deepcopy(doc)
    def measure(candidate):
        if candidate == doc:
            return row(0, 10)
        target = candidate['tube_joint']['target']
        value = candidate['tube_joint']['radial_clearance_mm']
        return row(0.6 if target == 'rear' and value == 0.5 else 0)
    monkeypatch.setattr(smart, 'measure_proximity', measure)
    outcome = smart.suggest(request(doc))
    assert outcome['outcome'] == 'candidate' and outcome['target'] == 'rear'
    assert doc == before
    parsed = _parse_suggestion({'status': 'ok', **outcome}, request(doc))
    assert parsed.after.pairs[0].distance_mm == pytest.approx(0.6)
    forged = deepcopy(outcome)
    forged['after'][0]['distance_mm'] = 0.1
    with pytest.raises(OverlapJobError):
        _parse_suggestion({'status': 'ok', **forged}, request(doc))


def test_no_guessed_requirement_and_unsupported_pair():
    doc = document()
    for bad in (None, -1, True, float('nan'), 101, 0.000001):
        value = request(doc)
        value['minimum_mm'] = bad
        with pytest.raises(ValueError):
            smart.validate_request(value)
    with pytest.raises(ValueError):
        smart.validate_request({**request(doc), 'right': 'housing_front'})


def test_failed_candidates_never_claim_success(monkeypatch):
    doc = document()
    monkeypatch.setattr(smart, 'measure_proximity', lambda candidate: row(0, 1))
    assert smart.suggest(request(doc))['outcome'] == 'no_candidate'
    monkeypatch.setattr(smart, 'measure_proximity', lambda candidate: row(0, 1e-7))
    assert smart.suggest(request(doc))['outcome'] == 'unverified'


def test_other_pair_cannot_gain_intersection(monkeypatch):
    from test_fixed_arm_housings import housings

    from suspensionlab.model.fixed_arm_housings import make_housing_preview

    doc = make_housing_preview(document(), housings())
    from itertools import combinations
    names = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    def rows(overlap):
        values = [{'left': a, 'right': b, 'distance_mm': 1, 'overlap_mm3': 0, 'threshold_mm3': 1e-6}
                  for a, b in combinations(names, 2)]
        values[0].update(distance_mm=0 if not overlap else 1, overlap_mm3=10 if not overlap else 0)
        if overlap:
            values[1].update(distance_mm=0, overlap_mm3=10)
        return values
    monkeypatch.setattr(smart, 'measure_proximity', lambda candidate: rows(candidate != doc))
    assert smart.suggest(request(doc))['outcome'] == 'no_candidate'


def test_actual_subprocess_only_returns_verified_or_no_candidate():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.core.cad_fixed_arm_overlap_job import FixedArmOverlapJob

    doc = document()
    result = FixedArmOverlapJob().run_suggestion(doc, 'tube_front', 'tube_rear', .5, timeout=90)
    assert result.outcome in ('no_candidate', 'candidate', 'already', 'unverified')
    if result.outcome == 'candidate':
        assert result.after.pairs[0].status == 'gap' and result.after.pairs[0].distance_mm >= .50001


def test_forged_already_satisfied_is_rejected():
    doc = document()
    with pytest.raises(OverlapJobError):
        _parse_suggestion({'status': 'ok', 'outcome': 'already', 'baseline': row(0, 1)}, request(doc))


def test_failed_candidate_is_reported_unverified(monkeypatch):
    doc = document()
    def measure(candidate):
        if candidate == doc:
            return row(0, 1)
        raise RuntimeError('CAD failed')
    monkeypatch.setattr(smart, 'measure_proximity', measure)
    assert smart.suggest(request(doc))['outcome'] == 'unverified'


def test_real_zero_clearance_candidate_has_no_computed_volume_and_does_not_mutate():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.core.cad_fixed_arm_overlap_job import FixedArmOverlapJob

    doc = document()
    before = deepcopy(doc)
    result = FixedArmOverlapJob().run_suggestion(doc, 'tube_front', 'tube_rear', 0, timeout=90)
    assert result.outcome == 'candidate'
    assert result.kind == 'joint' and result.radial_clearance_mm == 0
    assert result.after.pairs[0].status in ('near', 'gap') and result.after.pairs[0].overlap_mm3 == 0
    assert doc == before


def test_real_positive_clearance_candidate_rebuilds_all_pairs():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from test_fixed_arm_housings import housings

    from suspensionlab.core.cad_fixed_arm_overlap_job import FixedArmOverlapJob
    from suspensionlab.model.fixed_arm_housings import make_housing_preview

    h = housings()
    h['front']['axis'] = [1, 0, 0]
    h['front']['length_mm'] = 40
    doc = make_housing_preview(document(), h)
    original = deepcopy(doc)
    result = FixedArmOverlapJob().run_suggestion(doc, 'tube_front', 'housing_front', .5, timeout=90)
    assert result.outcome == 'candidate' and result.kind == 'housing' and result.target == 'front'
    assert result.after is not None and len(result.after.pairs) == 6
    pair = result.after.pairs[1]
    assert pair.status == 'gap' and pair.distance_mm >= .50001
    assert any(p.status == 'intersection' for p in result.after.pairs)  # Existing other conflicts stay visible.
    assert doc == original


def test_candidates_must_preserve_other_explicit_requirements(monkeypatch):
    from itertools import combinations

    from test_fixed_arm_housings import housings

    from suspensionlab.model.fixed_arm_housings import make_housing_preview

    doc = make_housing_preview(document(), housings())
    names = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    req = {'tube_front|tube_rear': 0.5, 'tube_front|housing_front': 2.0}
    params = {**request(doc), 'requirements': req}
    def measurements(candidate):
        values = [{'left': a, 'right': b, 'distance_mm': 3, 'overlap_mm3': 0, 'threshold_mm3': 1e-6}
                  for a, b in combinations(names, 2)]
        if candidate == doc:
            values[0].update(distance_mm=0, overlap_mm3=1)
        else:
            values[0].update(distance_mm=1, overlap_mm3=0)
            values[1]['distance_mm'] = 1  # still a gap, but violates another explicit minimum
        return values
    monkeypatch.setattr(smart, 'measure_proximity', measurements)
    assert smart.suggest(params)['outcome'] == 'no_candidate'
    candidate = smart.candidate_document(doc, 'joint', 'front', .5)
    forged = {'status': 'ok', 'outcome': 'candidate', 'baseline': measurements(doc), 'kind': 'joint',
              'target': 'front', 'radial_clearance_mm': .5, 'after': measurements(candidate)}
    with pytest.raises(OverlapJobError):
        _parse_suggestion(forged, params)
    with pytest.raises(ValueError):
        smart.validate_request({**params, 'minimum_mm': 1})


def test_candidate_options_expand_zero_and_existing_cuts_without_replacement():
    from suspensionlab.model.fixed_arm_housings import make_housing_preview

    doc = document()
    options, constrained = smart.candidate_options(doc, 'tube_front', 'tube_rear', 0)
    assert not constrained and {v for _, _, v in options} == {0, .5, 1, 2}
    existing = make_housing_preview(doc, None, None, {'target': 'rear', 'radial_clearance_mm': .75})
    options, constrained = smart.candidate_options(existing, 'tube_front', 'tube_rear', 0)
    assert constrained and options == [('joint', 'rear', 1.25), ('joint', 'rear', 1.75), ('joint', 'rear', 2.75)]
    capped = make_housing_preview(doc, None, None, {'target': 'rear', 'radial_clearance_mm': 100})
    assert smart.candidate_options(capped, 'tube_front', 'tube_rear', 0) == ([], True)
    options, _ = smart.candidate_options(doc, 'tube_front', 'tube_rear', 100)
    assert len(options) <= 12 and all(0 <= item[2] <= 100 for item in options)


def test_zero_requirement_can_use_larger_cut_not_guess_an_engineering_minimum(monkeypatch):
    doc = document()
    def measure(candidate):
        if candidate == doc:
            return row(0, 10)
        return row(0, 0 if candidate['tube_joint']['radial_clearance_mm'] == .5 else 10)
    monkeypatch.setattr(smart, 'measure_proximity', measure)
    req = {**request(doc), 'minimum_mm': 0}
    result = smart.suggest(req)
    assert result['outcome'] == 'candidate' and result['radial_clearance_mm'] == .5
    parsed = _parse_suggestion({'status': 'ok', **result}, req)
    assert parsed.after is not None and parsed.after.pairs[0].overlap_mm3 == 0
    forged = deepcopy(result)
    forged['radial_clearance_mm'] = .7
    with pytest.raises(OverlapJobError):
        _parse_suggestion({'status': 'ok', **forged}, req)


def test_reasons_report_observations_without_claiming_a_global_impossibility(monkeypatch):
    from itertools import combinations

    from test_fixed_arm_housings import housings

    from suspensionlab.model.fixed_arm_housings import make_housing_preview

    doc = make_housing_preview(document(), housings())
    names = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    def measured(candidate):
        rows = [{'left': a, 'right': b, 'distance_mm': 3, 'overlap_mm3': 0, 'threshold_mm3': 1e-6}
                for a, b in combinations(names, 2)]
        if candidate == doc:
            rows[0].update(distance_mm=0, overlap_mm3=1)
        else:
            rows[0].update(distance_mm=1, overlap_mm3=0)
            rows[1]['distance_mm'] = 1
        return rows
    monkeypatch.setattr(smart, 'measure_proximity', measured)
    req = {**request(doc), 'requirements': {'tube_front|tube_rear': .5, 'tube_front|housing_front': 2}}
    outcome = smart.suggest(req)
    assert outcome['outcome'] == 'no_candidate' and 'other_requirement' in outcome['reasons']
    assert _parse_suggestion({'status': 'ok', **outcome}, req).reasons == tuple(outcome['reasons'])
    forged = deepcopy(outcome)
    forged['reasons'] = ['unknown']
    with pytest.raises(OverlapJobError):
        _parse_suggestion({'status': 'ok', **forged}, req)
    forged['reasons'] = ['cad_error', 'cad_error']
    with pytest.raises(OverlapJobError):
        _parse_suggestion({'status': 'ok', **forged}, req)
    for invalid in ('unsupported', 'existing_cut', 'baseline_error', 'baseline_ambiguous', 'cad_error'):
        forged['reasons'] = [invalid]
        with pytest.raises(OverlapJobError):
            _parse_suggestion({'status': 'ok', **forged}, req)


def test_reason_existing_cut_limit_and_unsupported_pair(monkeypatch):
    from test_fixed_arm_housings import housings

    from suspensionlab.model.fixed_arm_housings import make_housing_preview

    capped = make_housing_preview(document(), None, None, {'target': 'rear', 'radial_clearance_mm': 100})
    monkeypatch.setattr(smart, 'measure_proximity', lambda candidate: row(0, 1))
    outcome = smart.suggest({**request(capped), 'minimum_mm': 0})
    assert outcome['outcome'] == 'no_candidate' and outcome['reasons'] == ['existing_cut']
    hdoc = make_housing_preview(document(), housings())
    from test_fixed_arm_auto import report
    # Convert to the worker's JSON pair representation.
    rows = [{'left': p.left, 'right': p.right, 'distance_mm': p.distance_mm,
             'overlap_mm3': p.overlap_mm3, 'threshold_mm3': p.threshold_mm3} for p in report().pairs]
    monkeypatch.setattr(smart, 'measure_proximity', lambda candidate: rows)
    outcome = smart.suggest({'document': hdoc, 'left': 'tube_front', 'right': 'housing_rear', 'minimum_mm': .5})
    assert outcome['outcome'] == 'no_candidate' and outcome['reasons'] == ['unsupported']


def test_real_existing_housing_cut_is_increased_and_all_pairs_checked():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from test_fixed_arm_housings import housings

    from suspensionlab.core.cad_fixed_arm_overlap_job import FixedArmOverlapJob
    from suspensionlab.model.fixed_arm_housings import make_housing_preview

    h = housings()
    h['front']['axis'] = [1, 0, 0]
    h['front']['length_mm'] = 40
    doc = make_housing_preview(document(), h, {'front': .5})
    before = deepcopy(doc)
    result = FixedArmOverlapJob().run_suggestion(doc, 'tube_front', 'housing_front', 1, timeout=90)
    assert result.outcome == 'candidate' and result.target == 'front' and result.radial_clearance_mm == 1.5
    assert result.after is not None and len(result.after.pairs) == 6
    assert result.after.pairs[1].distance_mm >= 1.00001 and doc == before
