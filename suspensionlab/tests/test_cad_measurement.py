"""Математика визуальных замеров; это не инженерная проверка STEP."""
import numpy as np
import pytest

from suspensionlab.core.cad_measurement import measurement_distance, point_on_projected_triangle
from suspensionlab.core.cad_raster import screen_projection


@pytest.mark.parametrize("yaw,elevation,zoom", [(0., 0., 1.), (0.6, -0.4, 2.), (-1.2, 0.7, 0.8)])
def test_interpolation_recovers_points_on_triangle_at_rotated_cameras(yaw, elevation, zoom):
    triangle = np.array([[10., -2., 5.], [20., 4., 6.], [14., 3., 19.]])
    center = np.array([11., 2., 3.])
    projected, _ = screen_projection(triangle[None], center, 20, yaw, elevation, zoom, 900, 600)
    for weights in ([0.2, 0.3, 0.5], [0., 0.4, 0.6], [1., 0., 0.], [0.1, 0.8, 0.1]):
        expected = np.array(weights) @ triangle
        x, y = np.array(weights) @ projected[0]
        point = point_on_projected_triangle(triangle, projected[0], float(x), float(y))
        assert point == pytest.approx(expected, abs=1e-9)
        # Противоположная ориентация грани не меняет точку.
        point = point_on_projected_triangle(triangle[::-1], projected[0][::-1], float(x), float(y))
        assert point == pytest.approx(expected, abs=1e-9)


def test_unusable_projection_and_outside_point_are_rejected():
    triangle = np.array([[0., 0., 0.], [2., 0., 0.], [0., 2., 1.]])
    projected = np.array([[0., 0.], [2., 0.], [0., 2.]])
    assert point_on_projected_triangle(triangle, projected, 1.5, 1.5) is None
    assert point_on_projected_triangle(triangle, np.zeros((3, 2)), 0., 0.) is None
    nearly_line = np.array([[0., 0.], [1000., 0.], [500., 1e-7]])
    assert point_on_projected_triangle(triangle, nearly_line, 500., 0.) is None
    assert point_on_projected_triangle(triangle, projected, float("nan"), 0.) is None
    assert point_on_projected_triangle(np.full((3, 3), np.nan), projected, 0., 0.) is None
    assert point_on_projected_triangle(triangle[:2], projected, 0., 0.) is None


def test_distance_uses_same_3d_frame_and_rejects_nonfinite_values():
    assert measurement_distance((1., 2., 3.), (4., 6., 3.)) == pytest.approx(5.)
    assert measurement_distance((1., 2., 3.), (1., 2., 3.)) == 0
    with pytest.raises(ValueError):
        measurement_distance((float("nan"), 0., 0.), (0., 0., 0.))
