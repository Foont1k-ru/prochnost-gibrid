"""Автообход не угадывает требования и не применяет независимые варианты."""
from copy import deepcopy
from itertools import combinations

import pytest
from test_fixed_arm_housings import housings
from test_fixed_arm_suggestions import document

from suspensionlab.core.cad_fixed_arm_overlap_job import (
    FixedArmOverlapJob,
    OverlapJobError,
    PairProximity,
    ProximityResult,
    SuggestionResult,
)
from suspensionlab.model.fixed_arm_housings import make_housing_preview


def report():
    names = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    return ProximityResult(tuple(PairProximity(a, b, 1 if i in (0, 1, 2) else 0, 1e-6,
                                              0 if i in (0, 1, 2) else 2)
                                 for i, (a, b) in enumerate(combinations(names, 2))))


def test_auto_checks_every_pair_without_guessing_and_keeps_working_after_failure(monkeypatch):
    doc = make_housing_preview(document(), housings())
    original = deepcopy(doc)
    base = report()
    job = FixedArmOverlapJob()
    calls = []
    monkeypatch.setattr(job, 'run_proximity', lambda doc: base)
    def suggest(doc, left, right, minimum, *, requirements):
        calls.append((left, right, minimum, requirements.copy()))
        if right == 'tube_rear':
            raise OverlapJobError('timeout')
        return SuggestionResult('no_candidate', base)
    monkeypatch.setattr(job, 'run_suggestion', suggest)
    req = {'tube_front|tube_rear': 0, 'tube_front|housing_front': .5,
           'tube_front|housing_rear': 1, 'housing_front|housing_rear': 3}
    result = job.run_auto(doc, req)
    assert [x.outcome for x in result.pairs] == ['failed', 'no_candidate', 'unsupported',
                                                  'no_requirement', 'no_requirement', 'unsupported']
    assert [x[:3] for x in calls] == [('tube_front', 'tube_rear', 0), ('tube_front', 'housing_front', .5)]
    assert all(x[3] == req for x in calls) and doc == original
    result = job.run_auto(doc, {})
    assert [x.outcome for x in result.pairs][:3] == ['requirement_missing'] * 3
    assert len(calls) == 2


def test_errors_and_ambiguous_pairs_block_suggestions(monkeypatch):
    doc = make_housing_preview(document(), housings())
    rows = list(report().pairs)
    rows[5] = PairProximity('housing_front', 'housing_rear', 1e-7, 1e-6, 0)
    job = FixedArmOverlapJob()
    monkeypatch.setattr(job, 'run_proximity', lambda doc: ProximityResult(tuple(rows)))
    monkeypatch.setattr(job, 'run_suggestion', lambda *a, **k: pytest.fail('ambiguous baseline'))
    result = job.run_auto(doc, {'tube_front|tube_rear': 0})
    assert result.pairs[0].outcome == 'unverified' and result.pairs[-1].outcome == 'unverified'


def test_cancel_stops_auto_between_pairs(monkeypatch):
    doc = make_housing_preview(document(), housings())
    job = FixedArmOverlapJob()
    base = report()
    monkeypatch.setattr(job, 'run_proximity', lambda doc: base)
    def cancel(*args, **kwargs):
        job.cancel()
        raise OverlapJobError('cancelled')
    monkeypatch.setattr(job, 'run_suggestion', cancel)
    with pytest.raises(OverlapJobError, match='cancelled'):
        job.run_auto(doc, {'tube_front|tube_rear': 0, 'tube_front|housing_front': .5})


def test_real_auto_finds_and_verifies_zero_candidate_without_mutating():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    doc = document()
    before = deepcopy(doc)
    result = FixedArmOverlapJob().run_auto(doc, {'tube_front|tube_rear': 0})
    entry = result.pairs[0]
    assert entry.outcome == 'candidate' and entry.suggestion is not None
    assert entry.suggestion.after is not None and entry.suggestion.after.pairs[0].overlap_mm3 == 0
    assert doc == before


def test_real_auto_with_multiple_requirements_produces_independent_checked_candidates():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.core.fixed_arm_suggestions import _requirements_not_worse, satisfies

    h = housings()
    h['front']['axis'] = [1, 0, 0]
    h['front']['length_mm'] = 40
    doc = make_housing_preview(document(), h)
    original = deepcopy(doc)
    req = {'tube_front|tube_rear': 0, 'tube_front|housing_front': .5}
    result = FixedArmOverlapJob().run_auto(doc, req)
    assert len(result.pairs) == 6
    assert [result.pairs[i].outcome for i in (0, 1)] == ['candidate', 'candidate']
    assert result.pairs[4].outcome == 'requirement_missing'
    for entry in result.pairs[:2]:
        assert entry.suggestion is not None and entry.suggestion.after is not None
        candidate = entry.suggestion
        assert candidate.after is not None
        for before, after in zip(candidate.baseline.pairs, candidate.after.pairs, strict=True):
            key = f'{before.left}|{before.right}'
            if key == f'{entry.left}|{entry.right}':
                assert satisfies(after, req[key])
            else:
                assert _requirements_not_worse(before, after, req.get(key))
    assert doc == original
