"""Независимые аналитические случаи для математики перемещения, не семантики STEP."""
from math import pi

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from suspensionlab.core.spatial_transform import RigidTransform, SpatialFrame


@pytest.fixture
def identity_frame():
    return SpatialFrame((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))


def test_known_active_rotation_translation_and_reverse(identity_frame):
    target = SpatialFrame((10, -2, 4), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    transform = RigidTransform.align_frames_same_units(identity_frame, target)
    assert transform.apply_point((2, 3, 5)) == pytest.approx((7, 0, 9))
    assert transform.apply_direction((2, 3, 5)) == pytest.approx((-3, 2, 5))
    assert transform.inverse().apply_point((7, 0, 9)) == pytest.approx((2, 3, 5))
    # Moving a frame is distinct from expressing the same point in that frame.
    assert transform.apply_point((0, 0, 0)) == pytest.approx((10, -2, 4))
    assert transform.inverse().apply_point((0, 0, 0)) == pytest.approx((2, 10, -4))


def test_nonidentity_source_frame_maps_axes_and_origin():
    source = SpatialFrame((4, 2, -1), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    target = SpatialFrame((-2, 3, 7), (0, 0, 1), (0, 1, 0), (-1, 0, 0))
    transform = RigidTransform.align_frames_same_units(source, target)
    assert transform.apply_point(source.origin) == pytest.approx(target.origin)
    for before, after in zip((source.x, source.y, source.z), (target.x, target.y, target.z), strict=True):
        assert transform.apply_direction(before) == pytest.approx(after)


def test_nested_composition_is_not_commutative(identity_frame):
    rotation = SpatialFrame((10, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    offset = SpatialFrame((2, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    parent = RigidTransform.align_frames_same_units(identity_frame, rotation)
    child = RigidTransform.align_frames_same_units(identity_frame, offset)
    assert parent.compose(child).apply_point((0, 0, 0)) == pytest.approx((10, 2, 0))
    assert child.compose(parent).apply_point((0, 0, 0)) == pytest.approx((12, 0, 0))
    assert parent.compose(child).apply_point((1, 0, 0)) == pytest.approx((10, 3, 0))


def test_independent_scipy_rotation_alignment_and_inverse():
    source_r = Rotation.from_euler("xyz", [0.37, -0.54, 0.91])
    target_r = Rotation.from_euler("xyz", [-1.1, 0.2, 0.4])
    def frame(rotation, origin):
        matrix = rotation.as_matrix()
        return SpatialFrame(origin, tuple(matrix[:, 0]), tuple(matrix[:, 1]), tuple(matrix[:, 2]))
    source = frame(source_r, (5., -8., 3.))
    target = frame(target_r, (-3., 9., 6.))
    result = RigidTransform.align_frames_same_units(source, target)
    reference = target_r * source_r.inv()
    point = np.array([2.3, -6.1, 10.8])
    expected = reference.apply(point - source.origin) + target.origin
    assert result.apply_point(tuple(point)) == pytest.approx(expected, abs=1e-9)
    assert result.inverse().apply_point(tuple(expected)) == pytest.approx(point, abs=1e-9)
    assert abs(reference.magnitude() - pi) > 0.1


@pytest.mark.parametrize("rotation,translation", [
    (((-1, 0, 0), (0, 1, 0), (0, 0, 1)), (0, 0, 0)),  # reflection
    (((2, 0, 0), (0, 1, 0), (0, 0, 1)), (0, 0, 0)),  # scale
    (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (float("nan"), 0, 0)),
    (((1, 0, 0), (0, 1, 0)), (0, 0, 0)),
    (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (float("inf"), 0, 0)),
])
def test_invalid_transforms_refused(rotation, translation):
    with pytest.raises(ValueError):
        RigidTransform(rotation, translation)


def test_invalid_frames_and_immutable_input():
    with pytest.raises(ValueError):
        SpatialFrame((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, -1))
    with pytest.raises(ValueError):
        SpatialFrame((0, 0, 0), (1, 0, 0), (1, 0, 0), (0, 0, 1))
    matrix = np.eye(3)
    offset = np.array([1., 2., 3.])
    transform = RigidTransform(matrix, offset)
    matrix[0, 0] = 5
    offset[0] = 100
    assert transform.apply_point((0, 0, 0)) == (1., 2., 3.)
    with pytest.raises(ValueError):
        transform.apply_point((float("nan"), 0, 0))
