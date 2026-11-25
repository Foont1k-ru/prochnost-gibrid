"""Изолированный анализ независимых CAD-тел, без преобразования в снимок."""
from copy import deepcopy
from itertools import combinations

import pytest
from test_free_arm_housing_io import make_draft
from test_free_arm_inner_housings import make_inner

from suspensionlab.core.cad_fixed_arm_overlap_job import (
    FixedArmOverlapJob,
    OverlapJobError,
    _parse_proximity,
)
from suspensionlab.core.cad_free_arm_overlap import independent_part_names
from suspensionlab.model.free_arm_housing_io import independent_arm_from_data
from suspensionlab.model.free_arm_housing_io import to_data as v2
from suspensionlab.model.free_arm_inner_housings_io import to_data as v3
from suspensionlab.model.free_arm_io import to_data as v1
from suspensionlab.model.free_arm_miter import FreeArmMiterDraft
from suspensionlab.model.free_arm_miter_io import to_data as v4
from suspensionlab.model.free_arm_tube_joint import FreeArmTubeJoint, FreeArmTubeJointDraft
from suspensionlab.model.free_arm_tube_joint_io import to_data as v5


def documents():
    arm = make_draft().arm
    inner = make_inner()
    return [
        (v1(arm), ('tube_front', 'tube_rear')),
        (v1(make_draft(('front',)).arm), ('tube_front', 'tube_rear')),
        (v2(make_draft()), ('tube_front', 'tube_rear', 'ball_housing')),
        (v3(inner), ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')),
        (v3(make_inner(ball=True)), ('tube_front', 'tube_rear', 'housing_front', 'housing_rear', 'ball_housing')),
        (v4(FreeArmMiterDraft(arm)), ('tube_front', 'tube_rear')),
        (v4(FreeArmMiterDraft(arm, inner.housings)), ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')),
        (v5(FreeArmTubeJointDraft(arm, FreeArmTubeJoint('rear', .5))), ('tube_front', 'tube_rear')),
        (v5(FreeArmTubeJointDraft(arm, FreeArmTubeJoint('front', .5), inner.housings)),
         ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')),
    ]


@pytest.mark.parametrize(('doc', 'names'), documents())
def test_names_and_strict_independent_version(doc, names):
    before = deepcopy(doc)
    assert independent_part_names(doc) == names
    assert independent_arm_from_data(doc) is not None and doc == before


@pytest.mark.parametrize(('doc', 'names'), documents())
def test_real_cad_and_isolated_process_match(doc, names):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.core.cad_fixed_arm_overlap import measure_proximity

    before = deepcopy(doc)
    direct = measure_proximity(doc)
    result = FixedArmOverlapJob().run_proximity(doc)
    assert [(p.left, p.right) for p in result.pairs] == list(combinations(names, 2))
    assert result == _parse_proximity(direct, doc)
    assert all(p.status != 'error' for p in result.pairs)
    assert doc == before


def test_malformed_result_rejected_and_input_not_modified():
    doc, _ = documents()[-1]
    before = deepcopy(doc)
    result = [{'left': left, 'right': right, 'error': 'measurement_failed'}
              for left, right in combinations(independent_part_names(doc), 2)]
    assert all(p.status == 'error' for p in _parse_proximity(result, doc).pairs)
    for mutation in ('missing', 'duplicate', 'unexpected', 'invalid_error'):
        bad = deepcopy(result)
        if mutation == 'missing':
            bad.pop()
        elif mutation == 'duplicate':
            bad[-1] = bad[0]
        elif mutation == 'unexpected':
            bad[0]['right'] = 'ball_housing'
        else:
            bad[0]['error'] = 'some_other_error'
        with pytest.raises(OverlapJobError):
            _parse_proximity(bad, doc)
    assert doc == before


@pytest.mark.parametrize('change', [
    lambda doc: doc.update(source='snapshot'),
    lambda doc: doc.update(version='6'),
    lambda doc: doc.update(extra=True),
    lambda doc: doc['joint'].update(radial_clearance_mm=-1),
])
def test_invalid_independent_input_rejected_before_worker(change):
    doc, _ = documents()[-1]
    change(doc)
    with pytest.raises(OverlapJobError, match='invalid'):
        FixedArmOverlapJob().run_proximity(doc)


def test_snapshot_operations_cannot_be_used_on_independent_document():
    doc, _ = documents()[-1]
    before = deepcopy(doc)
    for operation in (
        lambda: FixedArmOverlapJob().run(doc),
        lambda: FixedArmOverlapJob().run_all(doc),
        lambda: FixedArmOverlapJob().run_suggestion(doc, 'tube_front', 'tube_rear', 1),
        lambda: FixedArmOverlapJob().run_plan(doc, {}),
        lambda: FixedArmOverlapJob().run_auto(doc, {}),
    ):
        with pytest.raises(OverlapJobError, match='invalid'):
            operation()
    job = FixedArmOverlapJob()
    job.cancel()
    with pytest.raises(OverlapJobError, match='cancelled'):
        job.run_proximity(doc)
    assert doc == before


def test_failure_of_a_pair_is_not_a_zero_distance(monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.core import cad_fixed_arm_overlap as overlap

    doc, _ = documents()[0]
    monkeypatch.setattr(overlap, '_distance', lambda *_: (_ for _ in ()).throw(ValueError('failed')))
    measured = overlap.measure_proximity(doc)
    pair = _parse_proximity(measured, doc).pairs[0]
    assert pair.status == 'error' and pair.distance_mm is None and pair.overlap_mm3 is None


def test_actual_cuts_and_housings_change_measured_pairs():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    uncut = FixedArmOverlapJob().run_proximity(documents()[0][0]).pairs[0]
    miter = FixedArmOverlapJob().run_proximity(documents()[5][0]).pairs[0]
    housing = FixedArmOverlapJob().run_proximity(documents()[3][0]).pairs
    assert uncut.status == 'intersection' and uncut.overlap_mm3 > uncut.threshold_mm3
    assert miter.status == 'near' and miter.distance_mm == pytest.approx(0, abs=1e-6)
    front = next(p for p in housing if (p.left, p.right) == ('tube_front', 'housing_front'))
    assert front.status == 'gap' and front.distance_mm == pytest.approx(1, abs=1e-5)
    assert front.points is not None


def test_invalid_geometry_is_not_reported_as_partial_success():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from dataclasses import replace

    inner = make_inner()
    impossible = replace(inner, housings=replace(inner.housings,
        front=replace(inner.housings.front, outer_diameter_mm=1000, length_mm=2000)))
    doc = v3(impossible)
    before = deepcopy(doc)
    with pytest.raises(OverlapJobError, match='failed'):
        FixedArmOverlapJob().run_proximity(doc)
    assert doc == before
