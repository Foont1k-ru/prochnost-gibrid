"""Независимые аналитические и численные проверки отрезков/капсул."""
from math import dist

import numpy as np
import pytest
from scipy.optimize import minimize

from suspensionlab.core.segment_clearance import capsule_clearance, closest_segments


@pytest.mark.parametrize(('a', 'b', 'c', 'd', 'expected'), [
    ((0, 0, 0), (10, 0, 0), (5, -2, 0), (5, 2, 0), 0),
    ((0, 0, 0), (10, 0, 0), (5, -2, 3), (5, 2, 3), 3),
    ((0, 0, 0), (1, 0, 0), (3, 0, 0), (4, 0, 0), 2),
    ((0, 0, 0), (10, 0, 0), (2, 3, 0), (8, 3, 0), 3),
    ((0, 0, 0), (0, 0, 0), (2, -1, 0), (2, 1, 0), 2),
    ((0, 0, 0), (0, 0, 0), (1, 2, 2), (1, 2, 2), 3),
    ((0, 0, 0), (10, 0, 0), (10, 0, 0), (15, 1, 0), 0),
])
def test_analytic_cases_reversal_and_symmetry(a, b, c, d, expected):
    result = closest_segments(a, b, c, d)
    assert result.distance_mm == pytest.approx(expected, abs=1e-9)
    assert dist(result.first, result.second) == pytest.approx(expected, abs=1e-9)
    assert 0 <= result.first_parameter <= 1 and 0 <= result.second_parameter <= 1
    assert closest_segments(c, d, a, b).distance_mm == pytest.approx(expected, abs=1e-9)
    assert closest_segments(b, a, d, c).distance_mm == pytest.approx(expected, abs=1e-9)


def test_nearly_parallel_segments_can_cross_between_endpoints():
    a, b = (0., 0., 0.), (1000., 0., 0.)
    c, d = (0., -0.00001, 0.), (1000., 0.00001, 0.)
    result = closest_segments(a, b, c, d)
    assert result.distance_mm < 1e-11
    assert result.first_parameter == pytest.approx(.5, abs=1e-9)
    assert result.second_parameter == pytest.approx(.5, abs=1e-9)


def test_random_segments_agree_with_independent_bounded_optimizer():
    rng = np.random.default_rng(1809)
    for _ in range(100):
        coords = rng.uniform(-2000, 2000, size=(4, 3))
        a, b, c, d = coords
        def squared(st, a=a, b=b, c=c, d=d):
            delta = a + st[0] * (b - a) - c - st[1] * (d - c)
            return float(delta @ delta)
        fit = minimize(squared, (0.5, 0.5), method='L-BFGS-B', bounds=((0, 1), (0, 1)),
                       options={'ftol': 1e-15, 'gtol': 1e-8, 'maxiter': 300})
        result = closest_segments(*(tuple(float(x) for x in row) for row in coords))
        assert result.distance_mm ** 2 <= fit.fun + 1e-5
        assert result.distance_mm ** 2 == pytest.approx(fit.fun, rel=2e-7, abs=1e-5)


def test_capsule_classifications_are_based_on_explicit_radii_and_margin():
    a, b = (0., 0., 0.), (10., 0., 0.)
    def compare(offset, margin=2.):
        return capsule_clearance(a, b, 1., (0., offset, 0.), (10., offset, 0.), 1., margin)
    for offset, status, clearance in ((1., 'overlap', -1.), (2., 'touch', 0.),
                                      (3., 'low_clearance', 1.), (4., 'limit', 2.),
                                      (5., 'clear', 3.)):
        result = compare(offset)
        assert result.status == status
        assert result.clearance_mm == pytest.approx(clearance)
    assert compare(2., 0.).status == 'touch'


def test_rejects_nonfinite_invalid_sizes_and_coordinates():
    with pytest.raises(ValueError):
        closest_segments((True, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0))
    with pytest.raises(ValueError):
        closest_segments((0, 0, 0), (float('nan'), 0, 0), (0, 1, 0), (1, 1, 0))
    for radius in (True, 0, -1, float('inf'), float('nan'), 1_000_001):
        with pytest.raises(ValueError):
            capsule_clearance((0, 0, 0), (1, 0, 0), radius, (0, 1, 0), (1, 1, 0), 1, 0)
    for margin in (True, -1, float('nan')):
        with pytest.raises(ValueError):
            capsule_clearance((0, 0, 0), (1, 0, 0), 1, (0, 1, 0), (1, 1, 0), 1, margin)
