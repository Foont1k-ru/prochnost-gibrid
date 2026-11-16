"""Оценка массы одной стороны, не динамическая модель автомобиля."""
from math import inf, nan

import pytest

from suspensionlab.core.mass_load import GRAVITY_M_S2, symmetric_mass_load


def test_front_and_rear_use_selected_axle_and_unsprung_per_corner():
    front = symmetric_mass_load(1200, 55, 35)
    rear = symmetric_mass_load(1200, 45, 30)
    assert front.corner_total_kg == pytest.approx(330)
    assert front.corner_sprung_kg == pytest.approx(295)
    assert front.tire_reaction_n == pytest.approx(330 * GRAVITY_M_S2)
    assert front.sprung_load_n == pytest.approx(295 * GRAVITY_M_S2)
    assert rear.corner_total_kg == pytest.approx(270)
    assert rear.corner_sprung_kg == pytest.approx(240)
    assert rear.sprung_load_n == pytest.approx(240 * GRAVITY_M_S2)
    assert symmetric_mass_load(1200, 55, 0).sprung_load_n == pytest.approx(front.tire_reaction_n)


@pytest.mark.parametrize("mass,share,unsprung", [
    (0, 50, 10), (-1, 50, 10), (nan, 50, 10), (inf, 50, 10), (1000, 0, 10),
    (1000, 100, 10), (1000, nan, 10), (1000, inf, 10), (1000, 50, -1),
    (1000, 50, 250), (1000, 50, 251), (1000, 50, nan), (1000, 50, inf),
    (1e308, 50, 0),
])
def test_invalid_or_unrepresentable_inputs(mass, share, unsprung):
    with pytest.raises(ValueError):
        symmetric_mass_load(mass, share, unsprung)


def test_explicit_corner_load_has_no_symmetry_assumption_and_records_source():
    from suspensionlab.core.mass_load import corner_mass_load

    left = corner_mass_load(340, 40, "weighed")
    right = corner_mass_load(300, 35, "assumed")
    assert left.source_kind == "weighed" and right.source_kind == "assumed"
    assert left.corner_sprung_kg == 300 and right.corner_sprung_kg == 265
    assert left.tire_reaction_n == pytest.approx(340 * GRAVITY_M_S2)
    assert left.sprung_load_n == pytest.approx(300 * GRAVITY_M_S2)
    assert right.sprung_load_n == pytest.approx(265 * GRAVITY_M_S2)
    assert left.sprung_load_n != right.sprung_load_n


@pytest.mark.parametrize("wheel,unsprung", [
    (0, 0), (-1, 0), (nan, 0), (inf, 0), (1, -1), (1, 1), (1, 2), (1, nan),
    (1, inf), (1e308, 0), (5e-324, 5e-324),
])
def test_invalid_or_unrepresentable_corner_value(wheel, unsprung):
    from suspensionlab.core.mass_load import corner_mass_load

    with pytest.raises(ValueError):
        corner_mass_load(wheel, unsprung, "weighed")


def test_corner_source_must_be_explicit():
    from suspensionlab.core.mass_load import corner_mass_load

    with pytest.raises(ValueError):
        corner_mass_load(300, 35, "unknown")


@pytest.mark.parametrize("selected,expected", [
    ("front_left", 350), ("front_right", 300), ("rear_left", 250), ("rear_right", 200),
])
def test_four_wheel_totals_and_explicit_selection(selected, expected):
    from suspensionlab.core.mass_load import four_wheel_mass_load

    result = four_wheel_mass_load(350, 300, 250, 200, selected, 30, "weighed")
    assert result.total_kg == 1100 and result.front_kg == 650 and result.rear_kg == 450
    assert result.left_kg == 600 and result.right_kg == 500
    assert result.front_percent == pytest.approx(650 / 1100 * 100)
    assert result.rear_percent == pytest.approx(450 / 1100 * 100)
    assert result.corner_total_kg == expected and result.corner_sprung_kg == expected - 30
    assert result.sprung_load_n == pytest.approx((expected - 30) * GRAVITY_M_S2)
    assert result.tire_reaction_n == pytest.approx(expected * GRAVITY_M_S2)
    assert result.selected == selected and result.source_kind == "weighed"


@pytest.mark.parametrize("readings,selected,unsprung,source", [
    ((0, 300, 250, 200), "front_left", 30, "weighed"),
    ((350, nan, 250, 200), "front_left", 30, "weighed"),
    ((350, 300, inf, 200), "front_left", 30, "weighed"),
    ((350, 300, 250, -1), "front_left", 30, "weighed"),
    ((1e308, 1e308, 250, 200), "rear_left", 30, "weighed"),
    ((350, 300, 250, 200), "rear_left", 250, "weighed"),
    ((350, 300, 250, 200), "unknown", 30, "weighed"),
    ((350, 300, 250, 200), "rear_left", 30, "unknown"),
])
def test_four_wheel_rejects_missing_invalid_and_overflow(readings, selected, unsprung, source):
    from suspensionlab.core.mass_load import four_wheel_mass_load

    with pytest.raises(ValueError):
        four_wheel_mass_load(*readings, selected, unsprung, source)


@pytest.mark.parametrize("readings", [
    (250, 250, 250, 250),
    (350, 300, 250, 200),
    (150, 500, 200, 400),
    (1e-200, 1e200, 2e-200, 3e200),
])
def test_four_wheel_side_and_diagonal_shares(readings):
    from suspensionlab.core.mass_load import four_wheel_mass_load

    fl, fr, rl, rr = readings
    result = four_wheel_mass_load(*readings, "front_left", 0, "assumed")
    assert result.left_percent == pytest.approx((fl + rl) / result.total_kg * 100)
    assert result.right_percent == pytest.approx((fr + rr) / result.total_kg * 100)
    assert result.front_left_rear_right_kg == pytest.approx(fl + rr)
    assert result.front_right_rear_left_kg == pytest.approx(fr + rl)
    assert result.front_left_rear_right_percent == pytest.approx((fl + rr) / result.total_kg * 100)
    assert result.front_right_rear_left_percent == pytest.approx((fr + rl) / result.total_kg * 100)
    assert result.front_left_rear_right_percent + result.front_right_rear_left_percent == pytest.approx(100)


def test_diagonals_are_labelled_by_actual_wheels_not_selected_side():
    from suspensionlab.core.mass_load import four_wheel_mass_load

    first = four_wheel_mass_load(100, 200, 300, 400, "front_left", 0, "weighed")
    last = four_wheel_mass_load(100, 200, 300, 400, "rear_right", 0, "weighed")
    assert first.front_left_rear_right_kg == last.front_left_rear_right_kg == 500
    assert first.front_right_rear_left_kg == last.front_right_rear_left_kg == 500
