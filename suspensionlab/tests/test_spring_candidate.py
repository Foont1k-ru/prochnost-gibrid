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


def test_optional_linear_force_distinguishes_zero_conflict_missing_and_short_reserve():
    source = tuple(enumerate((None, 1., 100., 105., 110., 290., 300., 310.)))
    candidate = SpringCandidate(300, 200, 100, 10, 10, linear_rate_n_mm=20)
    result = compare_spring_candidate(source, 200, candidate)
    assert [p.status for p in result.points] == ["missing", "coil_bind", "coil_bind", "reserve_short", "clear",
                                                  "clear", "uncompressed", "uncompressed"]
    assert [p.force_n for p in result.points] == [None, None, None, 3900., 3800., 200., 0., 0.]
    assert [p.force_status for p in result.points] == ["missing", "coil_bind", "coil_bind", "calculated", "calculated",
                                                        "calculated", "calculated", "calculated"]
    disabled = compare_spring_candidate(source, 200, SpringCandidate(300, 200, 100, 10, 10))
    assert all(p.force_n is None and p.force_status == "disabled" for p in disabled.points)
    assert [p.status for p in disabled.points] == [p.status for p in result.points]


def test_force_invalid_length_boundaries_and_overflow():
    candidate = SpringCandidate(300, 50, 100, 0, 0, linear_rate_n_mm=10)
    result = compare_spring_candidate(((0, 1), (1, 250), (2, 400)), 200, candidate)
    assert result.points[0].status == "invalid" and result.points[0].force_status == "invalid"
    assert result.points[0].force_n is None
    assert result.points[1].length_mm == 100 and result.points[1].force_n is None
    assert result.points[2].length_mm == 250 and result.points[2].force_n == 500
    candidate = SpringCandidate(1e308, 2, 1, 0, 0, linear_rate_n_mm=1e308)
    result = compare_spring_candidate(((0, 2),), 2, candidate)
    assert result.points[0].force_n is None and result.points[0].force_status == "overflow"


@pytest.mark.parametrize("rate", [0, -1, inf, nan])
def test_invalid_candidate_linear_rate(rate):
    with pytest.raises(ValueError):
        SpringCandidate(300, 200, 100, 0, 0, linear_rate_n_mm=rate)


@pytest.mark.parametrize("length", [99.9, 100., 100.1, 150., 299.999, 300., 301., 500.])
@pytest.mark.parametrize("rate", [0.001, 1., 125.5, 10000.])
def test_linear_force_matches_explicit_formula_and_stop_rule(length, rate):
    candidate = SpringCandidate(300, 200, 100, 10, 10, linear_rate_n_mm=rate)
    point = compare_spring_candidate(((0, length),), 200, candidate).points[0]
    if length <= 100:
        assert point.force_n is None and point.force_status == "coil_bind"
    else:
        assert point.force_n == pytest.approx(rate * max(300 - length, 0))
        assert point.force_status == "calculated"


def test_force_summary_discrete_extrema_ties_and_missing_reasons():
    from suspensionlab.core.spring_candidate import summarize_candidate_force

    candidate = SpringCandidate(300, 50, 100, 0, 0, linear_rate_n_mm=10)
    source = ((0, None), (1, 1), (2, 250), (3, 400), (4, 500), (5, 400), (6, 450))
    summary = summarize_candidate_force(compare_spring_candidate(source, 200, candidate))
    assert (summary.total, summary.calculated, summary.missing, summary.invalid, summary.coil_bind) == (7, 4, 1, 1, 1)
    assert summary.minimum is not None and (summary.minimum.row, summary.minimum.force_n) == (4, 0)
    assert summary.maximum is not None and (summary.maximum.row, summary.maximum.force_n) == (3, 500)
    assert summary.maximum.travel_mm == 3 and summary.overflow == 0 and summary.disabled == 0


def test_force_summary_disabled_empty_overflow_and_no_values():
    from suspensionlab.core.spring_candidate import summarize_candidate_force

    disabled = compare_spring_candidate(((0, None), (1, 100)), 200, SpringCandidate(300, 200, 100, 0, 0))
    result = summarize_candidate_force(disabled)
    assert result.disabled == 2 and result.calculated == 0 and result.minimum is None and result.maximum is None
    empty = summarize_candidate_force(compare_spring_candidate((), 200, SpringCandidate(300, 200, 100, 0, 0, 1)))
    assert empty.total == 0 and empty.minimum is None and empty.maximum is None
    overflow = compare_spring_candidate(((0, 2),), 2, SpringCandidate(1e308, 2, 1, 0, 0, 1e308))
    result = summarize_candidate_force(overflow)
    assert result.overflow == 1 and result.minimum is None and result.maximum is None


def test_force_extrema_selected_before_display_rounding():
    from suspensionlab.core.spring_candidate import summarize_candidate_force

    candidate = SpringCandidate(300, 200, 100, 0, 0, 1)
    result = summarize_candidate_force(compare_spring_candidate(((0, 250), (1, 249.9999)), 200, candidate))
    assert result.maximum is not None and result.maximum.row == 1
    assert result.minimum is not None and result.minimum.row == 0
