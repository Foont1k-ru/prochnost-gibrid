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
    trimmed = trim_line((shapes[0], make_entity("arc", (0, 0), (5, 0), 90)), 0, (0, 0))
    assert len(trimmed) == 1 and trimmed[0].start == pytest.approx((5, 0))


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


def test_trim_arc_middle_into_two_arcs_and_undo():
    from suspensionlab.model.sketch_construction import trim_entity
    from suspensionlab.model.sketch_curves import point_at

    arc = make_entity("arc", (0, 0), (10, 0), 180)
    lines = (line((5, -20), (5, 20)), line((-5, -20), (-5, 20)))
    parts = trim_entity((arc, *lines), 0, (0, 10))
    assert len(parts) == 2 and all(e.kind == "arc" for e in parts)
    assert parts[0].sweep_deg == pytest.approx(60)
    assert parts[1].sweep_deg == pytest.approx(60)
    assert point_at(parts[0], 0) == pytest.approx((10, 0))
    assert point_at(parts[1], 1) == pytest.approx((-10, 0), abs=1e-12)
    draft = SketchDraft((arc, *lines))
    draft.replace_with(0, parts)
    draft.undo()
    assert tuple(draft.entities) == (arc, *lines)


def test_trim_clockwise_arc_and_arc_as_boundary():
    from suspensionlab.model.sketch_construction import trim_entity

    arc = make_entity("arc", (0, 0), (10, 0), -180)
    cutter = line((0, -15), (0, 15))
    parts = trim_entity((arc, cutter), 0, (7, -7))
    assert len(parts) == 1 and parts[0].sweep_deg == pytest.approx(-90)
    assert parts[0].end == pytest.approx((0, -10), abs=1e-12)
    # A finite arc cuts the line only at points actually on its sweep.
    base = line((-20, 0), (20, 0))
    short_arc = make_entity("arc", (0, 0), (10, 0), 90)
    result = trim_entity((base, short_arc), 0, (0, 0))
    assert result[0].start == pytest.approx((10, 0))


def test_arc_intersections_exclude_supporting_circle_and_overlap_is_safe():
    from suspensionlab.model.sketch_construction import trim_entity

    arc = make_entity("arc", (0, 0), (10, 0), 90)
    unrelated = line((-20, -5), (0, -5))  # crosses supporting circle, not the arc
    with pytest.raises(ValueError):
        trim_entity((unrelated, arc), 0, (-10, -5))
    overlap = make_entity("arc", (0, 0), (0, 10), -45)
    with pytest.raises(ValueError):
        trim_entity((arc, overlap, line((5, -20), (5, 20))), 0, (8, 5))


def test_near_coincident_arc_geometry_never_silently_trims():
    from suspensionlab.model.sketch_construction import trim_entity

    arc = make_entity("arc", (0, 0), (10, 0), 180)
    near_arc = make_entity("arc", (0.00000005, 0), (10.00000005, 0), 180)
    with pytest.raises(ValueError, match="Почти совпадающие"):
        trim_entity((arc, near_arc, line((0, -20), (0, 20))), 0, (7, 7))


def test_wraparound_arc_and_circle_as_cutter():
    from suspensionlab.model.sketch_construction import trim_entity
    from suspensionlab.model.sketch_curves import parameter, point_at

    arc = make_entity("arc", (0, 0), (0, -10), 180)  # -90° through 0° to 90°
    circle = make_entity("circle", (10, 0), (20, 0))
    parts = trim_entity((arc, circle), 0, (10, 0))
    assert len(parts) == 2
    assert all(part.sweep_deg == pytest.approx(30) for part in parts)
    assert parameter(arc, point_at(arc, 0.5)) == pytest.approx(0.5)


def test_arc_trimming_does_not_use_other_arc_extension():
    from suspensionlab.model.sketch_construction import trim_entity

    arc = make_entity("arc", (0, 0), (10, 0), 180)
    cutter = make_entity("arc", (10, 0), (20, 0), -90)  # intersection below, outside target
    with pytest.raises(ValueError):
        trim_entity((arc, cutter), 0, (0, 10))


def test_fillet_two_lines_is_tangent_and_undoable():
    from suspensionlab.model.sketch_construction import fillet_lines

    first, second = line((0, 0), (100, 0)), line((0, 100), (0, 0))
    a, b, arc = fillet_lines(first, second, 10)
    assert a.start == pytest.approx((10, 0)) and b.end == pytest.approx((0, 10))
    assert arc.start == pytest.approx((10, 10)) and arc.size == pytest.approx(10)
    assert arc_end(arc) == pytest.approx((0, 10), abs=1e-12)
    draft = SketchDraft((first, second))
    draft.apply_fillet(0, 1, (a, b, arc))
    assert len(draft.entities) == 3
    draft.undo()
    assert tuple(draft.entities) == (first, second)
    draft.redo()
    assert tuple(draft.entities) == (a, b, arc)


@pytest.mark.parametrize("first,second,radius", [
    (((0, 0), (10, 0)), ((0, 0), (0, 10)), 11),
    (((0, 0), (10, 0)), ((1, 0), (1, 10)), 1),
    (((0, 0), (10, 0)), ((0, 0), (-10, 0)), 1),
    (((0, 0), (10, 0)), ((0, 0), (0, 10)), 0),
])
def test_fillet_invalid_never_changes_input(first, second, radius):
    from suspensionlab.model.sketch_construction import fillet_lines

    with pytest.raises(ValueError):
        fillet_lines(line(*first), line(*second), radius)


@pytest.mark.parametrize("angle", [15, 45, 90, 120, 165, -45, -120])
def test_fillet_arbitrary_corner_is_tangent(angle):
    from suspensionlab.model.sketch_construction import fillet_lines

    theta = math.radians(angle)
    first = line((0, 0), (1000, 0))
    second = line((1000 * math.cos(theta), 1000 * math.sin(theta)), (0, 0))
    a, b, arc = fillet_lines(first, second, 10)
    p1, p2 = a.start, b.end
    r1, r2 = (p1[0] - arc.start[0], p1[1] - arc.start[1]), (p2[0] - arc.start[0], p2[1] - arc.start[1])
    v1, v2 = (a.end[0] - a.start[0], a.end[1] - a.start[1]), (b.end[0] - b.start[0], b.end[1] - b.start[1])
    assert abs(r1[0] * v1[0] + r1[1] * v1[1]) < 1e-6
    assert abs(r2[0] * v2[0] + r2[1] * v2[1]) < 1e-6
    assert arc_end(arc) == pytest.approx(p2, abs=1e-8)


@pytest.mark.parametrize("angle,at_end,reverse_line,inward", [(a, end, rev, inward)
    for a in (90, -90, 180, -180) for end in (False, True) for rev in (False, True) for inward in (False, True)])
def test_line_arc_fillet_is_finite_smooth_and_undoable(angle, at_end, reverse_line, inward):
    from suspensionlab.model.sketch_construction import fillet_line_arc
    from suspensionlab.model.sketch_curves import distance

    arc = make_entity("arc", (0, 0), (10, 0), angle)
    corner = arc_end(arc) if at_end else arc.end
    sign = -1 if inward else 1
    far = (corner[0] * (1 + sign), corner[1] * (1 + sign))
    source = line(far, corner) if reverse_line else line(corner, far)
    options = fillet_line_arc(source, arc, 2)
    assert options
    for new_line, new_arc, blend in options:
        p1, p2 = blend.end, arc_end(blend)
        assert min(distance(p1, new_line.start), distance(p1, new_line.end)) < 1e-8
        assert min(distance(p2, new_arc.end), distance(p2, arc_end(new_arc))) < 1e-8
        assert blend.size == pytest.approx(2)
        lv = (new_line.end[0] - new_line.start[0], new_line.end[1] - new_line.start[1])
        r1 = (p1[0] - blend.start[0], p1[1] - blend.start[1])
        assert r1[0] * lv[0] + r1[1] * lv[1] == pytest.approx(0, abs=1e-7)
        r2 = (p2[0] - blend.start[0], p2[1] - blend.start[1])
        ar = (p2[0] - arc.start[0], p2[1] - arc.start[1])
        assert r2[0] * ar[1] - r2[1] * ar[0] == pytest.approx(0, abs=1e-7)
        draft = SketchDraft((source, arc))
        draft.apply_fillet(0, 1, (new_line, new_arc, blend))
        draft.undo()
        assert tuple(draft.entities) == (source, arc)
        draft.redo()
        assert len(draft.entities) == 3


def test_line_arc_fillet_invalid_cases_leave_draft_untouched():
    from suspensionlab.model.sketch_construction import fillet_line_arc

    arc = make_entity("arc", (0, 0), (10, 0), 90)
    segment = line((10, 0), (15, 0))
    for radius in (0, -1, float("nan")):
        with pytest.raises(ValueError):
            fillet_line_arc(segment, arc, radius)
    assert not fillet_line_arc(segment, arc, 100)
    with pytest.raises(ValueError):
        fillet_line_arc(line((30, 0), (40, 0)), arc, 2)


def test_line_arc_fillet_preserves_closed_sector():
    from suspensionlab.model.sketch_construction import fillet_line_arc
    from suspensionlab.model.sketch_contours import check_contours

    segment = line((0, 0), (10, 0))
    arc = make_entity("arc", (0, 0), (10, 0), 90)
    third = line((0, 10), (0, 0))
    draft = SketchDraft((segment, arc, third))
    pieces = fillet_line_arc(segment, arc, 2)[0]
    draft.apply_fillet(0, 1, pieces)
    report = check_contours(tuple(draft.entities))
    assert report.total_issues == 0 and report.closed_loops == 1
