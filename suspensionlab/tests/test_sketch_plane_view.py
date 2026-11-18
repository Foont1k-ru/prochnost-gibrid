"""Независимые проверки геометрии выбора плоскостей."""

import pytest

from suspensionlab.model.sketch_plane_view import PLANES, camera_basis, dot, pick_plane, plane_point, project


@pytest.mark.parametrize("plane", PLANES)
def test_default_view_selects_each_visible_plane(plane):
    x, y, depth = project(plane_point(plane, 0.7, 0.7), 45, 35)
    assert depth > 0
    assert pick_plane(x, y, 45, 35) == plane


def test_projection_is_orthonormal_and_maps_axes_correctly():
    for yaw, pitch in [(45, 35), (0, 0), (123, -47), (290, 79)]:
        right, up, front = camera_basis(yaw, pitch)
        for v in (right, up, front):
            assert dot(v, v) == pytest.approx(1)
        assert dot(right, up) == pytest.approx(0, abs=1e-14)
        assert dot(right, front) == pytest.approx(0, abs=1e-14)
        assert dot(up, front) == pytest.approx(0, abs=1e-14)
    assert plane_point("XY", 2, 3) == (2, 3, 0)
    assert plane_point("XZ", 2, 3) == (2, 0, 3)
    assert plane_point("YZ", 2, 3) == (0, 2, 3)


def test_ray_picks_front_surface_when_visible_planes_overlap():
    # Looking from positive X and negative Y, both XY and XZ can overlap.
    x, y, _ = project(plane_point("XZ", 0.7, 0.7), -45, 35)
    assert pick_plane(x, y, -45, 35) == "XZ"
    # Reverse the view: the same projection intersects both in reverse order.
    x2, y2, _ = project(plane_point("XY", 0.7, 0.7), 135, -35)
    assert pick_plane(x2, y2, 135, -35) == "XY"


def test_blank_and_edge_on_plane_do_not_accidentally_select():
    assert pick_plane(0, 0, 45, 35) is None
    assert pick_plane(100, 100, 45, 35) is None
    x, y, _ = project(plane_point("XY", 0.6, 0.6), 0, 0)
    assert pick_plane(x, y, 0, 0) != "XY"
