import math

import numpy as np
import pytest

from suspensionlab.core.cad_registration import MAX_PAIRS, register_points


def test_known_rotation_translation_with_independent_holdout():
    # R: +90 degrees around Z; t: (120, -25, 40) mm.
    source = [(0, 0, 0), (100, 0, 0), (0, 50, 0), (0, 0, 25)]
    target = [(120, -25, 40), (120, 75, 40), (70, -25, 40), (120, -25, 65)]
    result = register_points(source, target)
    assert result.transform.apply_point((7, 11, 19)) == pytest.approx((109, -18, 59), abs=1e-10)
    assert result.rms_mm == pytest.approx(0, abs=1e-10)
    assert result.max_mm == pytest.approx(0, abs=1e-10)
    assert np.linalg.det(result.transform.rotation) == pytest.approx(1)


def test_no_scale_fit_and_residual_values():
    result = register_points([(0, 0, 0), (3, 0, 0), (0, 4, 0)], [(0, 0, 0), (6, 0, 0), (0, 8, 0)])
    assert result.rms_mm > 1
    assert result.max_mm == max(result.residuals_mm)
    assert result.rms_mm == pytest.approx(math.sqrt(sum(x*x for x in result.residuals_mm) / 3))
    assert result.transform.apply_direction((3, 0, 0)) == pytest.approx((3, 0, 0))


def test_no_reflection_fit_for_nonplanar_points():
    points = [(0, 0, 0), (10, 0, 0), (0, 20, 0), (0, 0, 30)]
    mirrored = [(-x, y, z) for x, y, z in points]
    result = register_points(points, mirrored)
    assert np.linalg.det(result.transform.rotation) == pytest.approx(1)
    assert result.rms_mm > 0.1


@pytest.mark.parametrize('points', [
    [(0, 0, 0)] * 3,
    [(0, 0, 0), (1, 0, 0), (2, 0, 0)],
    [(0, 0, 0), (1, 0, 0), (2, 1e-9, 0)],
    [(0, 0, 0), (0.0001, 0, 0), (0, 0.0001, 0)],
])
def test_degenerate_either_side(points):
    good = [(0, 0, 0), (100, 0, 0), (0, 100, 0)]
    for a, b in ((points, good), (good, points)):
        with pytest.raises(ValueError, match='degenerate'):
            register_points(a, b)


@pytest.mark.parametrize('a,b', [
    ([], []),
    ([(0, 0, 0)] * (MAX_PAIRS + 1), [(0, 0, 0)] * (MAX_PAIRS + 1)),
    ([(0, 0, 0)] * 3, [(0, 0, 0)] * 4),
    ([(0, 0)] * 3, [(0, 0)] * 3),
    ([(0, 0, float('nan')), (1, 0, 0), (0, 1, 0)], [(0, 0, 0)] * 3),
    ([(0, 0, 10_000_001), (1, 0, 0), (0, 1, 0)], [(0, 0, 0)] * 3),
    (['bad'] * 3, ['bad'] * 3),
])
def test_invalid_inputs_fail_closed(a, b):
    with pytest.raises(ValueError):
        register_points(a, b)


def test_arbitrary_points_match_independently_computed_errors():
    source = np.array([[0., 0., 0.], [100., 0., 0.], [0., 100., 0.], [0., 0., 100.]])
    target = source + np.array([10., 20., 30.])
    target[3] += [3., -5., 7.]
    result = register_points(source, target)
    distances = [math.dist(result.transform.apply_point(tuple(point)), tuple(expected))
                 for point, expected in zip(source, target, strict=True)]
    assert result.residuals_mm == pytest.approx(distances)
    assert result.rms_mm == pytest.approx(math.sqrt(sum(d*d for d in distances) / len(distances)))
