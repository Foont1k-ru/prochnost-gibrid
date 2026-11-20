"""Отчёт не принимает повреждённые, неполные и нечисловые значения."""
from copy import deepcopy
from itertools import combinations

import pytest

from suspensionlab.core.cad_fixed_arm_overlap_job import (
    DISTANCE_TOLERANCE_MM,
    FixedArmOverlapJob,
    OverlapJobError,
    PairProximity,
    _parse_proximity,
)
from suspensionlab.model.fixed_arm_housings import PREVIEW_FORMAT


def test_classification_distinguishes_ambiguous_volume_from_gap_and_failure():
    def pair(volume, threshold, distance):
        return PairProximity('tube_front', 'tube_rear', volume, threshold, distance)
    assert pair(0.1, 1e-6, 9).status == 'intersection'
    assert pair(1e-7, 1e-6, 9).status == 'uncertain_overlap'
    assert pair(0, 1e-6, DISTANCE_TOLERANCE_MM).status == 'near'
    assert pair(0, 1e-6, DISTANCE_TOLERANCE_MM * 2).status == 'gap'
    assert pair(None, None, None).status == 'error'


def test_parser_requires_all_pairs_and_distinguishes_pair_error():
    names = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    doc = {'format': PREVIEW_FORMAT, 'housings': {}}
    rows = [{'left': a, 'right': b, 'distance_mm': 2, 'overlap_mm3': 0, 'threshold_mm3': 1e-6}
            for a, b in combinations(names, 2)]
    assert len(_parse_proximity(rows, doc).pairs) == 6
    failure = deepcopy(rows)
    failure[2] = {'left': rows[2]['left'], 'right': rows[2]['right'], 'error': 'measurement_failed'}
    assert _parse_proximity(failure, doc).pairs[2].status == 'error'
    cases = [rows[:-1], list(reversed(rows))]
    for bad in (True, None, -1, float('nan'), float('inf'), 1e13, 10**1000):
        bad_row = deepcopy(rows)
        bad_row[0]['distance_mm'] = bad
        cases.append(bad_row)
    bad_row = deepcopy(rows)
    bad_row[0]['extra'] = 1
    cases.append(bad_row)
    bad_row = deepcopy(failure)
    bad_row[2]['error'] = 'different_error'
    cases.append(bad_row)
    for case in cases:
        with pytest.raises(OverlapJobError):
            _parse_proximity(case, doc)


def test_cancelled_job_rejects_before_start():
    job = FixedArmOverlapJob()
    job.cancel()
    with pytest.raises(OverlapJobError, match='cancelled'):
        job.run_proximity({})


def test_timeout_has_no_results():
    from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, fixed_arm_tube_document
    from suspensionlab.model.templates import load_template

    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    document = fixed_arm_tube_document(snapshot, project, 10, 2)
    with pytest.raises(OverlapJobError, match='timeout'):
        FixedArmOverlapJob().run_proximity(document, timeout=0.000001)
