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
