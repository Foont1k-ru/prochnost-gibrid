"""Сравнение кандидата по тем же рассчитанным опорам и явной длине в статике."""
from math import inf, nan, nextafter

import pytest

from suspensionlab.core.spring_candidate import SpringCandidate, compare_spring_candidate


def test_candidate_uses_separate_installed_length_and_preserves_missing_and_order():
    candidate = SpringCandidate(300, 210, 100, 10, 10)
    source = ((-10, 180.), (0, 200.), (10, 290.), (20, None))
    result = compare_spring_candidate(source, 200, candidate)
    assert [p.length_mm for p in result.points] == [190., 210., 300., None]
    assert [p.status for p in result.points] == ["clear", "clear", "uncompressed", "missing"]
    assert result.points[0].coil_clearance_mm == 90 and result.points[0].compression_mm == 110
    assert source[0] == (-10, 180.) and result.reference_installed_mm == 200


def test_exact_boundaries_priorities_and_reserves():
    candidate = SpringCandidate(300, 200, 100, 10, 10)
    values = (0.1, 100, 105, 110, 290, 295, 300, 301)
    result = compare_spring_candidate(tuple((i, v) for i, v in enumerate(values)), 200, candidate)
    assert [p.status for p in result.points] == ["coil_bind", "coil_bind", "reserve_short", "clear", "clear",
                                                  "reserve_short", "uncompressed", "uncompressed"]
    c = SpringCandidate(300, 200, 100, 0, 0)
    source = ((0, 100), (1, nextafter(100, inf)), (2, nextafter(300, 0)), (3, 300))
    assert [p.status for p in compare_spring_candidate(source, 200, c).points] == [
        "coil_bind", "clear", "clear", "uncompressed"]
    shifted = compare_spring_candidate(((0, 1), (1, None)), 200, SpringCandidate(300, 50, 100, 0, 0))
    assert shifted.points[0].length_mm == -149 and shifted.points[0].status == "invalid"
    assert shifted.points[1].length_mm is None and shifted.points[1].status == "missing"


@pytest.mark.parametrize("values", [(0, 200, 100, 0, 0), (300, 0, 100, 0, 0), (300, 200, 300, 0, 0),
                                     (300, 200, 0, 0, 0), (300, 200, 100, -1, 0), (300, 200, 100, 0, nan),
                                     (300, 200, inf, 0, 0)])
def test_invalid_candidate_inputs(values):
    with pytest.raises(ValueError):
        SpringCandidate(*values)


def test_invalid_source_and_overflow():
    candidate = SpringCandidate(300, 200, 100, 0, 0)
    for points, reference in [(((nan, 100),), 200), (((0, nan),), 200), (((0, 0),), 200), (((0, 100),), 0),
                              (((0, 1e308),), 200)]:
        if points[0][1] == 1e308:
            candidate = SpringCandidate(1e308, 1e308, 100, 0, 0)
        with pytest.raises(ValueError):
            compare_spring_candidate(points, reference, candidate)
