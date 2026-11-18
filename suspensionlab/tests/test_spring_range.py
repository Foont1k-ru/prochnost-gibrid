"""Дискретная сводка пружины, границы и недоступные результаты."""
from dataclasses import replace
from math import inf, nan, nextafter

import pytest

from suspensionlab.core.spring_characteristics import SpringCharacteristic, spring_state
from suspensionlab.core.spring_range import summarize_spring_range
from suspensionlab.ui.spring_range_text import spring_range_text


def test_summary_extremes_free_boundary_conflict_and_missing():
    c = SpringCharacteristic(300, 10, coil_bind_length_mm=100)
    states = [spring_state(c, length) for length in (320, 300, 250, 100, 99, 320)]
    summary = summarize_spring_range([(10, states[0]), (0, states[1]), (20, None), (-10, states[2]),
                                      (30, states[3]), (40, states[4]), (50, states[5])], 300, 100)
    assert (summary.total, summary.missing) == (7, 1)
    assert (summary.shortest.row, summary.shortest.travel_mm, summary.shortest.length_mm) == (5, 40, 99)
    assert (summary.longest.row, summary.longest.travel_mm, summary.longest.length_mm) == (0, 10, 320)
    assert summary.min_coil_clearance_mm == -1
    assert summary.coil_bind_count == 2
    assert (summary.free_boundary_count, summary.slack_count, summary.force_missing_count) == (1, 2, 2)
    assert summary.first_free.row == 0
    text = spring_range_text(summary)
    assert "пропусков: 1" in text and "строк на смыкании или за ним: 2" in text
    assert "На свободной длине: 1; длиннее свободной (без сжатия): 2" in text
    assert "выпадение или удержание" in text


def test_unknown_coil_all_missing_and_exact_float_boundaries():
    c = SpringCharacteristic(300, 10)
    below, above = nextafter(300, 0), nextafter(300, inf)
    summary = summarize_spring_range([(0, spring_state(c, below)), (1, spring_state(c, 300)),
                                      (2, spring_state(c, above)), (3, None)], 300, None)
    assert summary.coil_bind_count is None and summary.min_coil_clearance_mm is None
    assert (summary.free_boundary_count, summary.slack_count) == (1, 1)
    assert summary.first_free.row == 1
    text = spring_range_text(summary)
    assert "не проверены" in text and "На свободной длине: 1" in text
    assert "+300.000" not in text
    empty = summarize_spring_range([(0, None), (1, None)], 300, 100)
    assert empty.shortest is None and empty.longest is None and empty.first_free is None
    assert empty.missing == 2 and empty.min_coil_clearance_mm is None
    assert "Нет доступных" in spring_range_text(empty)


def test_force_undefined_distinct_from_length_available():
    c = SpringCharacteristic(300, 10, ((0, 0), (10, 100)))
    states = [spring_state(c, length) for length in (295, 290, 280)]
    assert [s.status for s in states] == ["loaded", "curve_knot", "outside_curve"]
    summary = summarize_spring_range([(i, s) for i, s in enumerate(states)], 300, None)
    assert summary.missing == 0 and summary.force_missing_count == 1
    summary = summarize_spring_range([(0, replace(states[0], force_n=inf))], 300, None)
    assert summary.force_missing_count == 1


@pytest.mark.parametrize("free, coil", [(nan, None), (0, None), (inf, None), (300, 0), (300, 300), (300, inf)])
def test_reject_invalid_limits(free, coil):
    with pytest.raises(ValueError):
        summarize_spring_range([], free, coil)


def test_reject_invalid_and_inconsistent_states():
    c = SpringCharacteristic(300, 10, coil_bind_length_mm=100)
    state = spring_state(c, 200)
    with pytest.raises(ValueError):
        summarize_spring_range([(nan, None)], 300, 100)
    with pytest.raises(ValueError):
        summarize_spring_range([(0, replace(state, length_mm=nan))], 300, 100)
    with pytest.raises(ValueError):
        summarize_spring_range([(0, state)], 300, 110)
    with pytest.raises(ValueError):
        summarize_spring_range([(0, replace(state, status="slack"))], 300, 100)
    with pytest.raises(ValueError):
        summarize_spring_range([(0, replace(state, status="coil_bind"))], 300, 100)
