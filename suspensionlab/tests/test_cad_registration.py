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


def test_independent_control_does_not_change_fit_and_reports_vector():
    from suspensionlab.core.cad_registration import evaluate_registration

    cad = [(0, 0, 0), (100, 0, 0), (0, 100, 0), (20, 30, 80)]
    # Identity on fitting pairs. Control target deliberately differs by (2, -3, 4).
    target = [(0, 0, 0), (100, 0, 0), (0, 100, 0), (22, 27, 84)]
    result = evaluate_registration(cad, target, (True, True, True, False))
    original = register_points(cad[:3], target[:3])
    assert result.fit.transform.rotation == original.transform.rotation
    assert result.fit.transform.translation == original.transform.translation
    assert result.fit.rms_mm == original.rms_mm
    assert result.points[3].predicted_mm == pytest.approx((20, 30, 80))
    assert result.points[3].delta_mm == pytest.approx((-2, 3, -4))
    assert result.control_rms_mm == pytest.approx(math.sqrt(29))
    assert result.control_max_mm == pytest.approx(math.sqrt(29))


def test_controls_can_reveal_mirror_hidden_by_fit_plane():
    from suspensionlab.core.cad_registration import evaluate_registration

    cad = [(0, 0, 0), (100, 0, 0), (0, 100, 0), (10, 20, 50)]
    reflected = [(x, y, -z) for x, y, z in cad]
    result = evaluate_registration(cad, reflected, (True, True, True, False))
    assert result.fit.rms_mm == pytest.approx(0, abs=1e-10)
    assert result.control_max_mm == pytest.approx(100)


def test_without_controls_is_explicit_and_control_order_is_preserved():
    from suspensionlab.core.cad_registration import evaluate_registration

    cad = [(0, 0, 0), (100, 0, 0), (0, 100, 0), (20, 30, 80), (10, 20, 20)]
    target = [cad[0], cad[1], cad[2], (23, 34, 80), (10, 20, 32)]
    no_control = evaluate_registration(cad[:3], target[:3], (True, True, True))
    assert no_control.control_rms_mm is None and no_control.control_max_mm is None
    mixed = evaluate_registration(cad, target, (True, True, True, False, False))
    assert mixed.points[3].distance_mm == pytest.approx(5)
    assert mixed.points[4].distance_mm == pytest.approx(12)
    assert mixed.control_rms_mm == pytest.approx(math.sqrt((25 + 144) / 2))
    assert mixed.control_max_mm == pytest.approx(12)


@pytest.mark.parametrize('mask', [(True, True, False), (True, True), (1, True, True)])
def test_control_mask_is_strict(mask):
    from suspensionlab.core.cad_registration import evaluate_registration

    pts = [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
    with pytest.raises(ValueError, match='count'):
        evaluate_registration(pts, pts, mask)


@pytest.mark.parametrize('duplicate_side', ['cad', 'target'])
def test_controls_cannot_repeat_coordinates(duplicate_side):
    from suspensionlab.core.cad_registration import evaluate_registration

    pts = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10)]
    duplicate = [*pts[:3], pts[0]]
    a, b = (duplicate, pts) if duplicate_side == 'cad' else (pts, duplicate)
    with pytest.raises(ValueError, match='duplicate'):
        evaluate_registration(a, b, (True, True, True, False))


def test_distance_comparison_separates_fit_and_all_control_segments():
    from suspensionlab.core.cad_registration import evaluate_registration

    cad = [(0, 0, 0), (3, 0, 0), (0, 4, 0), (0, 0, 12), (0, 0, 20)]
    project = [(10, 20, 30), (16, 20, 30), (10, 28, 30), (10, 20, 39), (10, 20, 55)]
    mask = (True, True, True, False, False)
    result = evaluate_registration(cad, project, mask)
    fit = result.fit_distances
    assert fit.count == 3
    assert (fit.first_row, fit.second_row) == (1, 2)
    assert (fit.cad_length_mm, fit.project_length_mm, fit.difference_mm) == pytest.approx((5, 10, 5))
    assert fit.rms_difference_mm == pytest.approx(math.sqrt((3**2 + 4**2 + 5**2) / 3))
    control = result.control_distances
    assert control is not None and control.count == 7  # 3x2 fit/control + 1 control/control
    segments = [(i, j, math.dist(cad[i], cad[j]), math.dist(project[i], project[j]))
                for i in range(5) for j in range(i + 1, 5) if not (mask[i] and mask[j])]
    expected = max(segments, key=lambda v: abs(v[3] - v[2]))
    assert (control.first_row, control.second_row) == expected[:2]
    assert control.difference_mm == pytest.approx(expected[3] - expected[2])
    assert control.rms_difference_mm == pytest.approx(
        math.sqrt(sum((p - c)**2 for _, _, c, p in segments) / 7))


def test_distance_diagnostics_ignore_rigid_transform_and_cannot_detect_reflection():
    from suspensionlab.core.cad_registration import evaluate_registration

    cad = [(0, 0, 0), (10, 0, 0), (0, 20, 0), (0, 0, 30)]
    mirror = [(100 - x, y - 50, z + 7) for x, y, z in cad]
    result = evaluate_registration(cad, mirror, (True, True, True, True))
    assert result.fit_distances.rms_difference_mm == pytest.approx(0)
    assert (result.fit_distances.first_row, result.fit_distances.second_row) == (0, 1)
    assert result.control_distances is None
    assert result.fit.rms_mm > 0.1  # distances alone cannot expose reflection


def test_distance_comparison_signed_shorter_project_and_control_not_in_fit_summary():
    from suspensionlab.core.cad_registration import evaluate_registration

    cad = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 100)]
    project = [(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 1)]
    result = evaluate_registration(cad, project, (True, True, True, False))
    assert result.fit_distances.rms_difference_mm == 0
    assert result.control_distances is not None
    assert result.control_distances.count == 3
    assert result.control_distances.difference_mm < 0
