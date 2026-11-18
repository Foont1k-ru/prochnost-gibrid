"""Справочные размерные линии используют CAD-границы, а не видимые линии."""
import math

import pytest

from suspensionlab.model.cad_projection_layout import format_reference_length, projection_layout


@pytest.mark.parametrize(('plane', 'expected', 'u_axis', 'v_axis'), [
    ('XY', (4., 6., -3., 2.), 'X', 'Y'),
    ('XZ', (4., 6., 11., 18.), 'X', 'Z'),
    ('YZ', (-3., 2., 11., 18.), 'Y', 'Z'),
])
def test_layout_bounds_orientation_and_isotropic_scale(plane, expected, u_axis, v_axis):
    bounds = (4., -3., 11., 6., 2., 18.)
    frame = projection_layout(bounds, plane, 200., 280.)
    assert (frame.u_min, frame.u_max, frame.v_min, frame.v_max) == expected
    assert frame.plane == u_axis + v_axis
    left, bottom = frame.screen(frame.u_min, frame.v_min)
    right, top = frame.screen(frame.u_max, frame.v_max)
    assert left >= 42 and right <= 190 and top >= 28 and bottom <= 235
    assert right > left and bottom > top
    assert (right - left) / frame.width_mm == pytest.approx((bottom - top) / frame.height_mm)
    assert frame.width_mm == pytest.approx(expected[1] - expected[0])
    assert frame.height_mm == pytest.approx(expected[3] - expected[2])


def test_fits_hidden_or_extreme_geometry_without_using_visible_contours():
    # The actual projected lines could be inside these bounds due to occlusion.
    bounds = (-800000., -5., 2., 800000., 5., 3.)
    for plane in ('XY', 'XZ', 'YZ'):
        frame = projection_layout(bounds, plane, 220., 300.)
        x1, y1 = frame.screen(frame.u_min, frame.v_min)
        x2, y2 = frame.screen(frame.u_max, frame.v_max)
        assert 42 <= x1 <= x2 <= 210
        assert 28 <= y2 <= y1 <= 255
        assert math.isfinite(frame.scale) and frame.scale > 0


@pytest.mark.parametrize('bounds,plane,width,height', [
    ((0., 0., 0., 1., 1., 1.), 'ZX', 200., 300.),
    ((0., 0., 0., 1., 0., 1.), 'XY', 200., 300.),
    ((0., 0., 0., 1., 1., math.inf), 'XY', 200., 300.),
    ((0., 0., 0., 1., 1., 1.), 'XY', 79., 300.),
    ((0., 0., 0., 1., 1., 1.), 'XY', 200., math.nan),
])
def test_invalid_bounds_or_viewport_rejected(bounds, plane, width, height):
    with pytest.raises(ValueError):
        projection_layout(bounds, plane, width, height)


def test_reference_rounding_does_not_claim_a_positive_dimension_is_zero():
    assert format_reference_length(0.001) == '<0.1'
    assert format_reference_length(0.049) == '<0.1'
    assert format_reference_length(2.04) == '2.0'
    assert format_reference_length(2.06) == '2.1'
    for invalid in (0., -1., math.inf, math.nan):
        with pytest.raises(ValueError):
            format_reference_length(invalid)


def test_dimension_segments_share_layout_axes_and_reference_captions():
    from suspensionlab.model.cad_projection_layout import dimension_segments, reference_caption

    frame = projection_layout((4., -3., 11., 6., 2., 18.), 'XZ', 200., 280.)
    x1, ybottom = frame.screen(4., 11.)
    x2, ytop = frame.screen(6., 18.)
    segments = dimension_segments(frame)
    assert len(segments) == 14
    assert segments[4] == pytest.approx((x1, ybottom + 13, x2, ybottom + 13))
    assert segments[5] == pytest.approx((x1 - 13, ytop, x1 - 13, ybottom))
    assert reference_caption('X', frame.width_mm) == 'X ≈ 2.0 мм'
    assert reference_caption('Z', frame.height_mm) == 'Z ≈ 7.0 мм'
    assert reference_caption('Y', 0.02) == 'Y <0.1 мм'
    with pytest.raises(ValueError):
        reference_caption('Q', 1.)
