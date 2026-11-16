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
    reverse = compare_mount_axes(spring[::-1], damper[::-1])
    assert reverse.angle_deg == result.angle_deg and reverse.lower_offset_mm == result.upper_offset_mm
    assert reverse.lower_pair_distance_mm == result.upper_pair_distance_mm
    assert reverse.upper_pair_distance_mm == result.lower_pair_distance_mm
    assert reverse.lower_axial_mm == -result.upper_axial_mm
    assert reverse.upper_axial_mm == -result.lower_axial_mm
    assert result.lower_pair_distance_mm == pytest.approx(425 ** 0.5)
    assert result.upper_pair_distance_mm == pytest.approx(425 ** 0.5)
    assert result.lower_axial_mm == result.upper_axial_mm == pytest.approx(20)
    # Coincident lines can have distinct mounting positions along the axis.
    displaced = compare_mount_axes(((0., 0., 20.), (0., 0., 30.)), damper)
    assert displaced.upper_offset_mm == displaced.lower_offset_mm == 0
    assert displaced.lower_pair_distance_mm == displaced.upper_pair_distance_mm == 20
    assert displaced.lower_axial_mm == displaced.upper_axial_mm == 20


def test_orthogonal_and_intersecting_axes():
    result = compare_mount_axes(((0., 0., 0.), (10., 0., 0.)), ((0., 0., 0.), (0., 0., 10.)))
    assert result.angle_deg == pytest.approx(90)
    assert result.lower_offset_mm == pytest.approx(0)
    assert result.upper_offset_mm == pytest.approx(10)
    assert result.lower_pair_distance_mm == 0 and result.lower_axial_mm == 0
    assert result.upper_pair_distance_mm == pytest.approx(200 ** 0.5)
    assert result.upper_axial_mm == pytest.approx(-10)
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
    assert transformed.lower_pair_distance_mm == pytest.approx(result.lower_pair_distance_mm, abs=1e-12)
    assert transformed.upper_pair_distance_mm == pytest.approx(result.upper_pair_distance_mm, abs=1e-12)
    assert transformed.lower_axial_mm == pytest.approx(result.lower_axial_mm, abs=1e-12)
    assert transformed.upper_axial_mm == pytest.approx(result.upper_axial_mm, abs=1e-12)


def test_small_angle_does_not_round_to_zero():
    result = compare_mount_axes(((0., 0., 0.), (1e-9, 0., 1.)), ((0., 0., 0.), (0., 0., 1.)))
    assert result.angle_deg == pytest.approx(5.729577951e-8, rel=1e-9)
    assert result.upper_offset_mm == pytest.approx(1e-9)


def test_signed_axial_and_pair_distance_for_oblique_axis():
    damper = ((0., 0., 0.), (0., 3., 4.))
    spring = ((3., 6., 8.), (3., -3., -4.))
    result = compare_mount_axes(spring, damper)
    assert result.lower_pair_distance_mm == pytest.approx(109 ** 0.5)
    assert result.lower_axial_mm == pytest.approx(10)
    assert result.lower_offset_mm == pytest.approx(3)
    assert result.upper_pair_distance_mm == pytest.approx(109 ** 0.5)
    assert result.upper_axial_mm == pytest.approx(-10)
    assert result.upper_offset_mm == pytest.approx(3)
    assert result.angle_deg == pytest.approx(0)  # Axes are not oriented for the angle.


def test_unrepresentable_distance_is_a_missing_comparison_not_infinite():
    axle = load_template("ring").front
    model = DoubleWishbone(axle, "left")
    frame = pose_view(model, model.solve(0), axle, spring=True, damper=True)
    frame = replace(frame, spring=((1e308, 0, 0), (1e308, 1, 0)),
                    damper=((-1e308, 0, 0), (-1e308, 1, 0)))
    row = compare_pose_axes(0, frame)
    assert row.status == "invalid_geometry" and row.result is None
