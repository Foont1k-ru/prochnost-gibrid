from dataclasses import replace
from math import inf, nan

import pytest

from suspensionlab.core.axis_alignment import compare_mount_axes, compare_pose_axes
from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.pose_view import pose_view
from suspensionlab.model.templates import load_template


def test_parallel_offset_and_orientation_independence():
    damper = ((0., 0., 0.), (0., 0., 10.))
    spring = ((3., 4., 20.), (3., 4., 30.))
    result = compare_mount_axes(spring, damper)
    assert result.angle_deg == pytest.approx(0)
    assert result.lower_offset_mm == result.upper_offset_mm == pytest.approx(5)
    assert result == compare_mount_axes(spring[::-1], damper[::-1])
    # Shift along the infinite line does not imply equal mount positions.
    assert compare_mount_axes(((0., 0., 20.), (0., 0., 30.)), damper).upper_offset_mm == 0


def test_orthogonal_and_intersecting_axes():
    result = compare_mount_axes(((0., 0., 0.), (10., 0., 0.)), ((0., 0., 0.), (0., 0., 10.)))
    assert result.angle_deg == pytest.approx(90)
    assert result.lower_offset_mm == pytest.approx(0)
    assert result.upper_offset_mm == pytest.approx(10)
    reverse = compare_mount_axes(((10., 0., 0.), (0., 0., 0.)), ((0., 0., 10.), (0., 0., 0.)))
    assert reverse.angle_deg == pytest.approx(90)
    assert reverse.lower_offset_mm == pytest.approx(10) and reverse.upper_offset_mm == pytest.approx(0)


@pytest.mark.parametrize("spring,damper", [
    (((0, 0, 0), (0, 0, 0)), ((0, 0, 0), (0, 0, 1))),
    (((0, 0, 0), (0, 0, 1)), ((0, 0, 1), (0, 0, 1))),
    (((0, 0, 0), (0, 0, nan)), ((0, 0, 0), (0, 0, 1))),
    (((inf, 0, 0), (0, 0, 1)), ((0, 0, 0), (0, 0, 1))),
    (((1e308, 0, 0), (-1e308, 0, 0)), ((0, 0, 0), (0, 0, 1))),
    (((0, 0), (0, 0, 1)), ((0, 0, 0), (0, 0, 1))),
])
def test_invalid_and_degenerate_axes(spring, damper):
    with pytest.raises(ValueError):
        compare_mount_axes(spring, damper)


def test_missing_pose_mounts_and_row_mismatch():
    axle = load_template("ring").front
    model = DoubleWishbone(axle, "left")
    frame = pose_view(model, model.solve(0), axle, spring=True, damper=True)
    assert compare_pose_axes(0, None).status == "missing_pose"
    assert compare_pose_axes(0, replace(frame, spring=None)).status == "missing_mounts"
    assert compare_pose_axes(0, replace(frame, damper=(frame.center, frame.center))).status == "invalid_geometry"
    assert compare_pose_axes(0, frame).status == "available"
    with pytest.raises(ValueError):
        compare_pose_axes(1, frame)
    with pytest.raises(ValueError):
        compare_pose_axes(nan, None)


def test_invariant_to_translation_rotation_and_mirroring():
    spring = ((2., 3., 4.), (7., 8., 13.))
    damper = ((4., 5., 6.), (6., 12., 14.))
    result = compare_mount_axes(spring, damper)
    # Permutation and reflection preserve Euclidean distances and unoriented angles.
    def change(point):
        x, y, z = point
        return (z + 100, -x - 300, y + 70)
    spring_transformed = (change(spring[0]), change(spring[1]))
    damper_transformed = (change(damper[0]), change(damper[1]))
    transformed = compare_mount_axes(spring_transformed, damper_transformed)
    assert transformed.angle_deg == pytest.approx(result.angle_deg, abs=1e-12)
    assert transformed.lower_offset_mm == pytest.approx(result.lower_offset_mm, abs=1e-12)
    assert transformed.upper_offset_mm == pytest.approx(result.upper_offset_mm, abs=1e-12)


def test_small_angle_does_not_round_to_zero():
    result = compare_mount_axes(((0., 0., 0.), (1e-9, 0., 1.)), ((0., 0., 0.), (0., 0., 1.)))
    assert result.angle_deg == pytest.approx(5.729577951e-8, rel=1e-9)
    assert result.upper_offset_mm == pytest.approx(1e-9)
