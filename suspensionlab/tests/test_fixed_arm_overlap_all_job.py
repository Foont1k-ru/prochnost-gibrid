"""Строгое принятие полного отчёта с неизменным порядком пар."""
from copy import deepcopy
from itertools import combinations

import pytest

from suspensionlab.core.cad_fixed_arm_overlap_job import (
    FixedArmOverlapJob,
    OverlapJobError,
    _parse_all_pairs,
)
from suspensionlab.model.fixed_arm_housings import PREVIEW_FORMAT


def rows(names):
    return [{'left': left, 'right': right, 'overlap_mm3': 0.0, 'threshold_mm3': 1e-6}
            for left, right in combinations(names, 2)]


def test_reports_exact_two_and_four_body_pair_sets():
    tube_names = ('tube_front', 'tube_rear')
    names = (*tube_names, 'housing_front', 'housing_rear')
    four = {'format': PREVIEW_FORMAT, 'housings': {}}
    two = {'format': PREVIEW_FORMAT, 'housings': None}
    assert len(_parse_all_pairs(rows(names), four).pairs) == 6
    assert len(_parse_all_pairs(rows(tube_names), two).pairs) == 1
    assert len(_parse_all_pairs(rows(tube_names), {'format': 'kima-assembly'}).pairs) == 1


def test_incomplete_duplicated_unknown_invalid_and_reordered_pairs_rejected():
    names = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    doc = {'format': PREVIEW_FORMAT, 'housings': {}}
    original = rows(names)
    cases = []
    cases.append(original[:-1])
    altered = deepcopy(original)
    altered[0] = deepcopy(altered[1])
    cases.append(altered)
    altered = deepcopy(original)
    altered[0]['left'] = 'fake'
    cases.append(altered)
    altered = deepcopy(original)
    altered.reverse()
    cases.append(altered)
    for bad in (True, float('nan'), float('inf'), -1, 1e25, 10**1000):
        altered = deepcopy(original)
        altered[0]['overlap_mm3'] = bad
        cases.append(altered)
    altered = deepcopy(original)
    altered[2]['threshold_mm3'] = 0
    cases.append(altered)
    altered = deepcopy(original)
    altered[3]['extra'] = 1
    cases.append(altered)
    for report in cases:
        with pytest.raises(OverlapJobError):
            _parse_all_pairs(report, doc)


def test_cancelled_all_pairs_never_runs():
    job = FixedArmOverlapJob()
    job.cancel()
    with pytest.raises(OverlapJobError, match='cancelled'):
        job.run_all({})
