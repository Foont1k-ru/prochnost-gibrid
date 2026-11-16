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
