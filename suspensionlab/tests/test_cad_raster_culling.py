"""Pixel equivalence of viewport culling with the original Pillow rendering path."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from suspensionlab.core import cad_raster


def _reference(projected, depth, shades, background, highlight, through, size):
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    order = np.argsort(depth, kind="stable")
    for index in order:
        color = (cad_raster.HIGHLIGHT_COLORS if highlight is not None and highlight[index]
                 else cad_raster.COLORS)[shades[index]]
        draw.polygon(projected[index].reshape(6).tolist(), fill=color)
    if through and highlight is not None:
        for index in order[highlight[order]]:
            draw.polygon(projected[index].reshape(6).tolist(), fill=cad_raster.HIGHLIGHT_COLORS[shades[index]])
    return np.asarray(image)


@pytest.mark.parametrize("zoom,offset", [(0.25, (0., 0.)), (1., (14., -9.)), (4., (200., -70.))])
@pytest.mark.parametrize("highlight_mode", ["none", "normal", "through"])
def test_random_scene_matches_original(zoom, offset, highlight_mode):
    rng = np.random.default_rng(6249)
    centers = rng.uniform(-8, 8, (2200, 1, 3))
    triangles = centers + rng.normal(0, 0.4, (2200, 3, 3))
    shades = rng.integers(105, 206, len(triangles), dtype=np.uint8)
    highlight = None if highlight_mode == "none" else rng.random(len(triangles)) < 0.2
    through = highlight_mode == "through"
    center = np.zeros(3)
    size = (137, 93)
    projected, depth = cad_raster._screen_projection_depth(triangles, center, 8., .8, -.2, zoom, *size, 24., offset)
    expected = _reference(projected, depth, shades, (11, 13, 17), highlight, through, size)
    actual = cad_raster.rasterize(triangles, shades, center, 8., .8, -.2, zoom, *size, (11, 13, 17),
                                   highlight=highlight, through=through, offset=offset)
    assert np.array_equal(np.asarray(actual), expected)


@pytest.mark.parametrize("through", [False, True])
def test_fractional_borders_degenerate_and_equal_depth(monkeypatch, through):
    size = (31, 19)
    x = [-2., -1., -.999, -.5, 0., .5, 30., 30.99, 31., 32.]
    y = [-2., -1., -.999, -.5, 0., .5, 18., 18.99, 19., 20.]
    # Point-like and thin triangles on both sides, plus lines crossing the frame.
    shapes = [[[v, -0.5], [v, 10.], [v, 20.]] for v in x]
    shapes += [[[-.5, v], [15., v], [32., v]] for v in y]
    shapes += [[[a, b], [a, b], [a, b]] for a in x for b in y]
    shapes += [[[-30., -20.], [70., -20.], [15., 50.]], [[-100., 9.], [100., 9.], [0., 9.]]]
    projected = np.tile(np.asarray(shapes, dtype=float), (12, 1, 1))
    count = len(projected)
    # Equal depths deliberately exercise stable overlap ordering.
    depth = np.arange(count) % 4
    shades = np.arange(count, dtype=np.int64) % 256
    highlight = np.arange(count) % 3 == 0
    monkeypatch.setattr(cad_raster, "_screen_projection_depth", lambda *args: (projected, depth))
    expected = _reference(projected, depth, shades, (9, 12, 18), highlight, through, size)
    actual = cad_raster.rasterize(np.zeros((count, 3, 3)), shades, np.zeros(3), 1., 0., 0., 1., *size,
                                  (9, 12, 18), highlight=highlight, through=through)
    assert np.array_equal(np.asarray(actual), expected)


@pytest.mark.parametrize("nan_index", [0, 1])
def test_nonfinite_projection_keeps_reference_behavior(monkeypatch, nan_index):
    projected = np.full((1000, 3, 2), 100.)
    projected[nan_index, 0, 0] = np.nan
    depth = np.zeros(1000)
    shades = np.zeros(1000, dtype=np.uint8)
    monkeypatch.setattr(cad_raster, "_screen_projection_depth", lambda *args: (projected, depth))
    expected = _reference(projected, depth, shades, (0, 0, 0), None, False, (31, 19))
    actual = cad_raster.rasterize(np.zeros((1000, 3, 3)), shades, np.zeros(3),
                                  1., 0., 0., 1., 31, 19, (0, 0, 0))
    assert np.array_equal(np.asarray(actual), expected)
