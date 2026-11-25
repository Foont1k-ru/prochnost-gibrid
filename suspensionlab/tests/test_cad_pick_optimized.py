"""Оптимизированный выбор совпадает с прежним полным стабильным порядком отрисовки."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from suspensionlab.core.cad_raster import pick_triangle, screen_projection


def reference_pick(triangles, center, radius, yaw, elevation, zoom, width, height, x, y,
                   margin=24., highlight=None, through=False, offset=(0., 0.)):
    if not (0 <= x < width and 0 <= y < height):
        return None
    projected, order = screen_projection(triangles, center, radius, yaw, elevation, zoom,
                                         width, height, margin, offset)
    coords = np.trunc(projected).astype(np.int64)
    hit = ((coords[:, :, 0].min(axis=1) <= x) & (coords[:, :, 0].max(axis=1) >= x) &
           (coords[:, :, 1].min(axis=1) <= y) & (coords[:, :, 1].max(axis=1) >= y))
    candidates = order[hit[order]]
    image = Image.new('RGB', (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    for identifier, index in enumerate(candidates, 1):
        draw.polygon(coords[index].reshape(6).tolist(), fill=(identifier >> 16, (identifier >> 8) & 255, identifier & 255))
    if through and highlight is not None:
        for identifier, index in enumerate(candidates, 1):
            if highlight[index]:
                draw.polygon(coords[index].reshape(6).tolist(), fill=(identifier >> 16, (identifier >> 8) & 255, identifier & 255))
    red, green, blue = image.getpixel((x, y))
    value = (red << 16) | (green << 8) | blue
    return int(candidates[value - 1]) if 0 < value <= len(candidates) else None


@pytest.mark.parametrize('through', [False, True])
@pytest.mark.parametrize('view', [(0., 0., 1., (0., 0.)), (.7, -.4, 1.5, (20., -15.)),
                                   (1.57, .8, .7, (-40., 30.))])
def test_matches_original_draw_order_with_overlap_ties_and_offsets(through, view):
    rng = np.random.default_rng(8052)
    triangles = rng.uniform(-4., 4., (600, 3, 3))
    # Coincident depths, overlapping boundaries and a degenerate triangle are intentional.
    triangles[1] = triangles[0]
    triangles[2] = triangles[0, 0]
    highlight = rng.random(len(triangles)) < .2
    yaw, elevation, zoom, offset = view
    args = (triangles, np.zeros(3), 4., yaw, elevation, zoom, 160, 120)
    for x, y in ((0, 0), (159, 119), (80, 60), (81, 60), (30, 25), (100, 90), (-1, 0), (160, 60)):
        expected = reference_pick(*args, x, y, highlight=highlight, through=through, offset=offset)
        assert pick_triangle(*args, x, y, highlight=highlight, through=through, offset=offset) == expected


def test_equal_depth_respects_original_order_and_through_highlight():
    triangles = np.tile(np.array([[[-2., 0, -2], [2., 0, -2], [0, 0, 2]]]), (10, 1, 1))
    args = (triangles, np.zeros(3), 3., 0., 0., 1., 100, 100, 50, 50)
    highlight = np.zeros(10, dtype=bool)
    highlight[3] = True
    assert pick_triangle(*args) == 9
    assert pick_triangle(*args, highlight=highlight, through=True) == 3
