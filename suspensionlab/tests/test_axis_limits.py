from math import inf, nan, nextafter

import pytest

from suspensionlab.core.axis_alignment import AxisLimits, check_axis_limits, compare_mount_axes


@pytest.mark.parametrize("values", [(-1, None, None), (90.00001, None, None), (nan, None, None),
                                    (inf, None, None), (None, -1, None), (None, None, -1), (None, inf, None)])
def test_invalid_limits(values):
    with pytest.raises(ValueError):
        AxisLimits(*values)


def test_none_partial_complete_and_exact_boundaries():
    result = compare_mount_axes(((3., 4., 20.), (3., 4., 30.)), ((0., 0., 0.), (0., 0., 10.)))
    assert check_axis_limits(result, AxisLimits()).combined == "unchecked"
    partial = check_axis_limits(result, AxisLimits(angle_deg=0))
    assert (partial.angle, partial.lower, partial.upper, partial.combined) == ("within", "unchecked", "unchecked", "partial")
    distance = result.lower_pair_distance_mm
    all_equal = check_axis_limits(result, AxisLimits(0, distance, distance))
    assert (all_equal.angle, all_equal.lower, all_equal.upper, all_equal.combined) == ("within", "within", "within", "within")
    beyond = check_axis_limits(result, AxisLimits(0, nextafter(distance, 0), distance))
    assert (beyond.lower, beyond.upper, beyond.combined) == ("exceeded", "within", "exceeded")
    assert check_axis_limits(None, AxisLimits(0, 0, 0)).combined == "missing"
    assert check_axis_limits(None, AxisLimits()).angle == "missing"
    assert AxisLimits(90, 0, 0).angle_deg == 90


def test_maxima_use_unrounded_values_first_tie_and_skip_missing():
    from dataclasses import replace

    from suspensionlab.core.axis_alignment import AxisAlignmentRow, summarize_axis_maxima

    original = compare_mount_axes(((0., 0., 0.), (0., 0., 10.)), ((0., 0., 0.), (0., 0., 10.)))
    low = replace(original, angle_deg=1.00001, lower_pair_distance_mm=5., upper_pair_distance_mm=7.)
    high = replace(original, angle_deg=1.00002, lower_pair_distance_mm=8., upper_pair_distance_mm=6.)
    rows = (AxisAlignmentRow(-1., None, "missing_pose"), AxisAlignmentRow(0., low, "available"),
            AxisAlignmentRow(1., high, "available"), AxisAlignmentRow(2., high, "available"))
    result = summarize_axis_maxima(rows)
    assert result.angle is not None and result.angle.row == 2 and result.angle.value == 1.00002
    assert result.lower is not None and result.lower.row == 2 and result.lower.value == 8.
    assert result.upper is not None and result.upper.row == 1 and result.upper.value == 7.
    empty = summarize_axis_maxima((rows[0],))
    assert empty.angle is None and empty.lower is None and empty.upper is None
