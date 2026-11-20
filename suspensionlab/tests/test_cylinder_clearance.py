"""Аналитические и независимые численные проверки конечного цилиндра."""
from math import sqrt

import numpy as np
import pytest
from scipy.optimize import minimize

from suspensionlab.core.cylinder_clearance import capsule_cylinder_clearance


@pytest.mark.parametrize(('a', 'b', 'expected'), [
    ((3., 0., -1.), (3., 0., 1.), 2.),  # radial wall
    ((0., 0., 4.), (0., 0., 5.), 2.),  # end cap
    ((3., 0., 4.), (4., 0., 5.), sqrt(8)),  # corner
    ((-3., 0., 0.), (3., 0., 0.), 0.),  # crosses cylinder
    ((0., 0., 0.), (0., 0., 0.), 0.),
    ((-3., 1., 0.), (3., 1., 0.), 0.),  # tangent to cylindrical wall
])
def test_axis_distance_to_cylinder(a, b, expected):
    result = capsule_cylinder_clearance(a, b, .25, (0., 0., 0.), (0., 0., 10.), 1., 4., 0.)
    assert result.clearance_mm == pytest.approx(expected - .25, abs=1e-8)
    assert 0 <= result.axis_parameter <= 1
    reverse = capsule_cylinder_clearance(b, a, .25, (0., 0., 0.), (0., 0., -1.), 1., 4., 0.)
    assert reverse.clearance_mm == pytest.approx(result.clearance_mm, abs=1e-8)


def test_translated_and_rotated_cylinder():
    rotated = capsule_cylinder_clearance((9., 23., 30.), (11., 23., 30.), .25,
                                         (10., 20., 30.), (5., 0., 0.), 1., 4., 0.)
    assert rotated.clearance_mm == pytest.approx(1.75, abs=1e-8)
    assert rotated.status == 'clear'


def test_classifications_and_not_penetration_depth():
    def get(x, margin):
        return capsule_cylinder_clearance((x, 0., -1.), (x, 0., 1.), 1., (0., 0., 0.), (0., 0., 1.), 1., 4., margin)
    for x, status in ((1.5, 'overlap'), (2., 'touch'), (3., 'low_clearance'), (4., 'limit'), (5., 'clear')):
        assert get(x, 2.).status == status
    # For an axis inside, -radius is not the depth needed to separate the solids.
    assert get(0., 0.).clearance_mm == pytest.approx(-1.)


def test_random_against_constrained_3d_optimization():
    rng = np.random.default_rng(7801)
    for _ in range(60):
        a, b = rng.uniform(-5, 5, (2, 3))
        radius, half = rng.uniform(.2, 3, 2)
        # Independent four-variable minimization: t plus cylinder point (x,y,z).
        def squared(q, a=a, b=b):
            v = a + q[0] * (b - a) - q[1:4]
            return float(v @ v)
        fit = minimize(squared, (0.5, 0., 0., 0.), method='SLSQP',
                       bounds=((0, 1), (-radius, radius), (-radius, radius), (-half, half)),
                       constraints=({'type': 'ineq', 'fun': lambda q, r=radius: r*r-q[1]**2-q[2]**2},),
                       options={'ftol': 1e-11, 'maxiter': 500})
        assert fit.success
        result = capsule_cylinder_clearance(tuple(map(float, a)), tuple(map(float, b)), .1, (0., 0., 0.), (0., 0., 1.),
                                             float(radius), float(2*half), 0.)
        assert (result.clearance_mm + .1) ** 2 == pytest.approx(fit.fun, rel=1e-5, abs=1e-7)


def test_rejects_invalid_cylinder_or_dimensions():
    args = ((0., 0., 0.), (1., 0., 0.), 1., (0., 0., 0.), (0., 0., 1.), 1., 2., 0.)
    for index, value in ((2, 0), (5, -1), (6, 0), (6, True), (7, float('nan')), (4, (0., 0., 0.))):
        modified = list(args)
        modified[index] = value
        with pytest.raises(ValueError):
            capsule_cylinder_clearance(*modified)
