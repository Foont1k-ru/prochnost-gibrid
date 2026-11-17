"""Первый 3D-предпросмотр: ограниченная замкнутая сетка, не CAD-тело."""

import numpy as np
import pytest

from suspensionlab.model.sketch_draft import make_entity, rectangle_entities
from suspensionlab.model.sketch_extrusion import extrusion_mesh
from suspensionlab.model.sketch_io import SketchDocument


def document(entities, plane="XY", offset=3):
    return SketchDocument(plane, offset, tuple(entities))


@pytest.mark.parametrize("plane,expected", [("XY", ((0, 0, 3), (10, 20, 8))),
                                             ("XZ", ((0, 3, 0), (10, 8, 20))),
                                             ("YZ", ((3, 0, 0), (8, 10, 20)))])
def test_extrude_rectangle_all_planes(plane, expected):
    mesh = extrusion_mesh(document(rectangle_entities((0, 0), (10, 20)), plane), 5)
    assert mesh.shape == (12, 3, 3)
    assert np.min(mesh, axis=(0, 1)) == pytest.approx(expected[0])
    assert np.max(mesh, axis=(0, 1)) == pytest.approx(expected[1])
    # Oriented triangle mesh encloses positive volume for each basis.
    assert sum(np.dot(t[0], np.cross(t[1], t[2])) for t in mesh) / 6 == pytest.approx(1000)


def test_circle_and_arc_are_approximated():
    circle = make_entity("circle", (0, 0), (10, 0))
    mesh = extrusion_mesh(document((circle,)), 5)
    assert mesh.shape == (4 * 96 - 4, 3, 3)
    arc = make_entity("arc", (0, 0), (10, 0), 180)
    segment = make_entity("line", (-10, 0), (10, 0))
    mesh = extrusion_mesh(document((arc, segment)), 5)
    assert len(mesh) > 12
    assert np.isfinite(mesh).all()


def test_concave_contour_caps_have_correct_volume():
    points = [(0, 0), (10, 0), (10, 3), (3, 3), (3, 10), (0, 10)]
    segments = [make_entity("line", points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
    mesh = extrusion_mesh(document(segments), 5)
    assert sum(np.dot(t[0], np.cross(t[1], t[2])) for t in mesh) / 6 == pytest.approx(255)


@pytest.mark.parametrize("depth", [0, -1, float("inf"), float("nan"), 1000001])
def test_bad_depth_rejected(depth):
    with pytest.raises(ValueError):
        extrusion_mesh(document(rectangle_entities((0, 0), (10, 20))), depth)


def test_open_or_multiple_contours_rejected():
    with pytest.raises(ValueError):
        extrusion_mesh(document((make_entity("line", (0, 0), (1, 1)),)), 5)
    outer = make_entity("circle", (0, 0), (10, 0))
    inner = make_entity("circle", (0, 0), (3, 0))
    with pytest.raises(ValueError):
        extrusion_mesh(document((outer, inner)), 5)


def test_mesh_is_closed_and_winding_consistent_with_fillet():
    from collections import Counter

    from suspensionlab.model.sketch_construction import fillet_lines
    from suspensionlab.model.sketch_draft import SketchDraft

    draft = SketchDraft(rectangle_entities((0, 0), (100, 40)))
    draft.apply_fillet(0, 1, fillet_lines(draft.entities[0], draft.entities[1], 10))
    mesh = extrusion_mesh(document(draft.entities), 4)
    edges = Counter()
    for triangle in mesh:
        vertices = [tuple(p) for p in triangle]
        for i in range(3):
            edges[tuple(sorted((vertices[i], vertices[(i + 1) % 3])))] += 1
    assert set(edges.values()) == {2}


def test_unordered_and_reversed_edges_accepted():
    r = rectangle_entities((0, 0), (10, 20))
    reverse = lambda e: make_entity("line", e.end, e.start)  # noqa: E731
    mesh = extrusion_mesh(document((reverse(r[2]), r[0], reverse(r[3]), r[1])), 2)
    assert len(mesh) == 12
