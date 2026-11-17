"""Проверка контуров не исправляет данные и не является CAD-валидацией."""

import math

import pytest

from suspensionlab.model.sketch_contours import MAX_CHECK_ENTITIES, MAX_REPORTED_ISSUES, check_contours
from suspensionlab.model.sketch_draft import make_entity, rectangle_entities


def line(a, b):
    return make_entity("line", a, b)


def circle(center, radius):
    return make_entity("circle", center, (center[0] + radius, center[1]))


def codes(report):
    return {issue.code for issue in report.issues}


def test_closed_rectangle_and_nested_circle():
    rect = rectangle_entities((0, 0), (100, 100))
    entities = (*rect, circle((50, 50), 10))
    report = check_contours(entities)
    assert not report.issues
    assert report.closed_loops == 2
    assert entities == (*rect, circle((50, 50), 10))


def test_empty_open_and_gap_not_silently_closed():
    assert codes(check_contours(())) == {"empty"}
    a = line((0, 0), (10, 0))
    assert codes(check_contours((a,))) == {"open"}
    b = line((10.005, 0), (10, 10))
    report = check_contours((a, b))
    assert "gap" in codes(report) and "open" in codes(report)
    assert report.closed_loops is None
    assert any(issue.points for issue in report.issues)


def test_branches_crossings_overlaps_and_t_junctions():
    branch = (line((-1, 0), (0, 0)), line((0, 0), (1, 0)), line((0, 0), (0, 1)))
    assert "branch" in codes(check_contours(branch))
    crossing = (line((-1, 0), (1, 0)), line((0, -1), (0, 1)))
    assert "contact" in codes(check_contours(crossing))
    overlap = (line((0, 0), (10, 0)), line((5, 0), (15, 0)))
    assert "contact" in codes(check_contours(overlap))
    t_junction = (line((0, 0), (10, 0)), line((5, 0), (5, 10)))
    assert "contact" in codes(check_contours(t_junction))


@pytest.mark.parametrize("shapes", [
    (circle((0, 0), 10), circle((20, 0), 10)),  # tangent
    (circle((0, 0), 10), circle((0, 0), 10)),  # duplicate
    (circle((0, 0), 10), circle((5, 0), 10)),
    (circle((0, 0), 10), line((-20, 0), (20, 0))),
    (circle((0, 0), 10), line((-20, 10), (20, 10))),
    (circle((0, 0), 10), line((0, 0), (10, 0))),
])
def test_circle_contacts_are_reported(shapes):
    assert "contact" in codes(check_contours(shapes))


def test_disjoint_and_nested_no_circle_contact():
    shapes = (circle((0, 0), 100), circle((0, 0), 10), circle((200, 0), 10))
    report = check_contours(shapes)
    assert not report.issues and report.closed_loops == 3


def test_circle_radius_is_analytic_and_defining_point_is_not_vertex():
    shape = circle((0, 0), 10)
    report = check_contours((shape, line((0, 0), (1, 0))))
    assert "contact" not in codes(report)


def test_cap_and_tolerance():
    small = line((0, 0), (0.002, 0))
    assert "small" in codes(check_contours((small,), 0.01))
    for value in (0, -1, 2, math.nan, math.inf):
        with pytest.raises(ValueError):
            check_contours((), value)
    with pytest.raises(ValueError):
        check_contours((small,) * (MAX_CHECK_ENTITIES + 1))


def test_report_is_bounded():
    shapes = (circle((0, 0), 10),) * 40
    report = check_contours(shapes)
    assert len(report.issues) == MAX_REPORTED_ISSUES
    assert report.total_issues == 40 * 39 // 2


def test_two_valid_rectangles_and_intersecting_loops():
    left = rectangle_entities((0, 0), (20, 20))
    right = rectangle_entities((30, 0), (50, 20))
    clean = check_contours((*left, *right))
    assert clean.closed_loops == 2 and not clean.issues
    crossing = rectangle_entities((10, 10), (30, 30))
    report = check_contours((*left, *crossing))
    assert report.closed_loops is None
    assert "contact" in codes(report)


def test_tolerance_does_not_merge_and_exact_coincidence_is_accepted():
    original = list(rectangle_entities((0, 0), (10, 10)))
    original[0] = line((0, 0), (10.005, 0))
    report = check_contours(tuple(original), 0.01)
    assert "gap" in codes(report) and report.closed_loops is None
    assert original[0].end == (10.005, 0)
    assert check_contours(rectangle_entities((0, 0), (10, 10))).closed_loops == 1


def test_line_line_disjoint_near_contact_and_valid_adjacent_collinear():
    disjoint = (line((0, 0), (1, 0)), line((2, 0), (3, 0)))
    assert "contact" not in codes(check_contours(disjoint))
    near = (line((0, 0), (10, 0)), line((2, .005), (8, .005)))
    assert "contact" in codes(check_contours(near))
    subdivided = (line((0, 0), (5, 0)), line((5, 0), (10, 0)),
                  line((10, 0), (10, 10)), line((10, 10), (0, 10)), line((0, 10), (0, 0)))
    assert check_contours(subdivided).closed_loops == 1
