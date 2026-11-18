"""Мелкая управляемая сетка хода и защита от чрезмерного размера."""
import math

import pytest

from suspensionlab.core.sweep import travel_grid


@pytest.mark.parametrize("bounds", [(-35, 40), (-2.5, 1.2), (0, 1), (-4, -1), (1, 2), (0, 0)])
def test_default_grid_includes_endpoints_and_static(bounds: tuple[float, float]) -> None:
    points = travel_grid(*bounds)
    assert points[0] == bounds[0] and points[-1] == bounds[1]
    assert all(0 < b - a <= 1.00000000001 for a, b in zip(points, points[1:], strict=False))
    if bounds[0] <= 0 <= bounds[1]:
        assert 0 in points


def test_submillimetre_grid_and_limits() -> None:
    points = travel_grid(-1, 1, max_spacing_mm=0.1)
    assert len(points) == 21 and 0 in points
    assert max(b - a for a, b in zip(points, points[1:], strict=False)) == pytest.approx(0.1)
    for args in ((0, 1, 0), (2, 1, 1), (0, math.inf, 1), (0, 1000, 0.01), (-3000, 3000, 1)):
        with pytest.raises(ValueError):
            travel_grid(args[0], args[1], max_spacing_mm=args[2])
