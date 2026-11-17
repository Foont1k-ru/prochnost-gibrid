"""Обрезка и касания: геометрические построения без зависимостей."""

import math

import pytest

from suspensionlab.model.sketch_construction import tangent_circles, trim_line
from suspensionlab.model.sketch_draft import SketchDraft, arc_end, make_entity


def line(a, b):
    return make_entity("line", a, b)


def test_two_tangencies_all_solutions_on_finite_segments():
    lines = (line((-10, 0), (10, 0)), line((0, -10), (0, 10)))
    circles = tangent_circles(lines, 2)
    assert len(circles) == 4
    assert {(round(c.start[0]), round(c.start[1])) for c in circles} == {(-2, -2), (-2, 2), (2, -2), (2, 2)}
    assert all(math.isclose(c.size, 2) for c in circles)
    assert tangent_circles((line((0, 0), (1, 0)), lines[1]), 2) == ()
    assert tangent_circles((line((0, 0), (10, 0)), line((0, 10), (10, 10))), 5) == ()


def test_three_tangencies_triangle_incircle():
    lines = (line((0, 0), (10, 0)), line((10, 0), (0, 10)), line((0, 10), (0, 0)))
    circles = tangent_circles(lines)
    assert len(circles) == 1
    assert math.isclose(circles[0].size, 10 / (2 + math.sqrt(2)))
    assert math.isclose(circles[0].start[0], circles[0].start[1])
    assert tangent_circles((lines[0], lines[0], lines[1])) == ()


def test_trim_between_two_crossing_lines_and_undo_redo():
    shapes = (line((0, 0), (10, 0)), line((3, -5), (3, 5)), line((7, -5), (7, 5)))
    parts = trim_line(shapes, 0, (5, 0))
    assert len(parts) == 2 and parts[0].end == (3, 0) and parts[1].start == (7, 0)
    draft = SketchDraft(shapes)
    draft.replace_with(0, parts)
    assert len(draft.entities) == 4
    draft.undo()
    assert tuple(draft.entities) == shapes
    draft.redo()
    assert len(draft.entities) == 4
    with pytest.raises(ValueError):
        trim_line(shapes, 0, (3, 0))


def test_trim_at_circle_and_reject_ambiguous():
    shapes = (line((-10, 0), (10, 0)), make_entity("circle", (0, 0), (5, 0)))
    parts = trim_line(shapes, 0, (0, 0))
    assert parts[0].end == (-5, 0) and parts[1].start == (5, 0)
    with pytest.raises(ValueError):
        trim_line((shapes[0], line((-5, 0), (5, 0))), 0, (0, 0))
    with pytest.raises(ValueError):
        trim_line((shapes[0],), 0, (0, 0))
    with pytest.raises(ValueError):
        trim_line((shapes[0], make_entity("arc", (0, 0), (5, 0), 90)), 0, (0, 0))


def test_arc_direction_and_validation():
    for angle, expected in ((90, (0, 5)), (-90, (0, -5)), (180, (-5, 0))):
        entity = make_entity("arc", (0, 0), (5, 0), angle)
        assert arc_end(entity) == pytest.approx(expected, abs=1e-12)
    for angle in (0, 360, -360, float("nan")):
        with pytest.raises(ValueError):
            make_entity("arc", (0, 0), (5, 0), angle)


def test_trim_circle_to_arc_and_undo():
    from suspensionlab.model.sketch_construction import trim_entity

    shapes = (make_entity("circle", (0, 0), (10, 0)), line((-20, 0), (20, 0)))
    remaining = trim_entity(shapes, 0, (0, 10))
    assert len(remaining) == 1 and remaining[0].kind == "arc"
    assert remaining[0].sweep_deg == pytest.approx(180)
    assert remaining[0].end == pytest.approx((-10, 0), abs=1e-12)
    assert arc_end(remaining[0]) == pytest.approx((10, 0), abs=1e-12)
    draft = SketchDraft(shapes)
    draft.replace_with(0, remaining)
    draft.undo()
    assert tuple(draft.entities) == shapes


def test_trim_circle_circle_and_tangent_guard():
    from suspensionlab.model.sketch_construction import trim_entity

    c1 = make_entity("circle", (0, 0), (10, 0))
    c2 = make_entity("circle", (10, 0), (20, 0))
    assert trim_entity((c1, c2), 0, (10, 0))[0].kind == "arc"
    tangent = line((-20, 10), (20, 10))
    with pytest.raises(ValueError):
        trim_entity((c1, tangent), 0, (0, -10))
    with pytest.raises(ValueError):
        trim_entity((c1, c1), 0, (0, 10))
