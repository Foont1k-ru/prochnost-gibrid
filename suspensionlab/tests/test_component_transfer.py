"""Перенос длин не должен скрыто округлять или ограничивать данные."""
from __future__ import annotations

from math import inf, nan

import pytest

from suspensionlab.ui.component_transfer import transferable_damper_lengths


def check(a: float, b: float, decimals: int = 1) -> tuple[float, float]:
    return transferable_damper_lengths(a, b, minimum=0, maximum=2000, decimals=decimals)


def test_preserves_full_input_values():
    assert check(280.1, 420.9) == (280.1, 420.9)
    assert check(0.1, 2000) == (0.1, 2000)
    assert check(205.125, 325.125, decimals=3) == (205.125, 325.125)


@pytest.mark.parametrize("a,b", [(0, 325), (-1, 325), (325, 325), (330, 325),
                                   (nan, 325), (205, inf), (inf, 325), (205, nan)])
def test_invalid_physical_limits_are_rejected(a, b):
    with pytest.raises(ValueError, match="Перенос невозможен"):
        check(a, b)


def test_range_and_precision_are_not_silently_changed():
    with pytest.raises(ValueError, match="ограничения значения"):
        check(100, 2000.1)
    with pytest.raises(ValueError, match="округления"):
        check(205.125, 325)
    with pytest.raises(ValueError, match="округления"):
        check(205, 325.04)
    with pytest.raises(ValueError):
        check(1, 3, decimals=13)
