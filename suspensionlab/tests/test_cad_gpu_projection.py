"""Сравнение подготовки будущей GPU-камеры с существующей CPU-проекцией."""
import numpy as np
import pytest

from suspensionlab.core.cad_gpu_projection import clip_matrix, normalized_vertices
from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_raster import screen_projection


@pytest.mark.parametrize("yaw,elevation,zoom,width,height,ratio,pan", [
    (0., 0., 1., 800, 600, 1., (0., 0.)),
    (-0.65, 0.35, 1.3, 641, 823, 1.5, (123., -40.)),
    (3.14, -1.5, 4., 250, 1600, 2., (-50., 63.)),
    (-2., 1.57, 0.25, 10, 7, 1., (0., 0.)),
])
def test_clip_matrix_matches_cpu_projection(yaw, elevation, zoom, width, height, ratio, pan):
    rng = np.random.default_rng(144)
    # Большой сдвиг проверяет центрирование до преобразования в float32.
    triangles = rng.uniform(-100., 100., (90, 3, 3)) + [9990000., -9990000., 9990000.]
    mesh = CadMesh(triangles, 1)
    center, radius = mesh.bounds()
    offset = tuple(v * ratio for v in pan)
    margin = 24 * ratio
    expected, _ = screen_projection(mesh.triangles, center, radius, yaw, elevation, zoom, width, height,
                                    margin=margin, offset=offset)
    points = normalized_vertices(mesh.triangles, center, radius).astype(np.float64)
    homogeneous = np.concatenate((points, np.ones((*points.shape[:2], 1))), axis=2)
    clip = homogeneous @ clip_matrix(yaw, elevation, zoom, width, height, margin, offset).T
    pixel = np.stack(((clip[:, :, 0] + 1) * width / 2, (1 - clip[:, :, 1]) * height / 2), axis=2)
    np.testing.assert_allclose(pixel, expected, rtol=0, atol=0.0002)


def test_normalization_does_not_modify_input_or_lose_small_features():
    triangles = np.array([[[9999999., 0., 0.], [9999999.1, 0., 0.], [9999999., 0.1, 0.]]])
    before = triangles.copy()
    result = normalized_vertices(triangles, np.array([9999999., 0., 0.]), 1.)
    assert result.dtype == np.float32 and result.flags.c_contiguous
    assert result[0, 1, 0] == pytest.approx(0.1)
    np.testing.assert_array_equal(triangles, before)


@pytest.mark.parametrize("kwargs", [
    {"yaw": float('nan')}, {"elevation": float('inf')}, {"zoom": 0.}, {"width": 0},
    {"height": -1}, {"margin": -1.}, {"offset": (float('inf'), 0.)},
])
def test_bad_camera_rejected(kwargs):
    args = {"yaw": 0., "elevation": 0., "zoom": 1., "width": 200, "height": 300}
    args.update(kwargs)
    with pytest.raises(ValueError):
        clip_matrix(**args)


def test_normalization_processes_multiple_chunks():
    rng = np.random.default_rng(19)
    points = rng.normal(size=(4097, 3, 3)) + [10000., 20000., 30000.]
    center = np.array([10000., 20000., 30000.])
    result = normalized_vertices(points, center, 5.)
    np.testing.assert_allclose(result, ((points - center) / 5.).astype(np.float32), atol=0, rtol=0)


def test_bad_mesh_and_bounds_rejected():
    points = np.zeros((1, 3, 3))
    with pytest.raises(ValueError):
        normalized_vertices(points, np.zeros(3), 0)
    with pytest.raises(ValueError):
        normalized_vertices(np.full((1, 3, 3), np.nan), np.zeros(3), 1)
    with pytest.raises(ValueError):
        normalized_vertices(points, np.array([0., np.inf, 0.]), 1)
