"""Изолированная геометрия пробного эскиза."""

import math

import pytest

from suspensionlab.model.sketch_draft import SketchDraft, make_entity


def test_line_circle_and_history():
    draft = SketchDraft()
    draft.add("line", (0, 0), (3, 4))
    draft.add("circle", (10, 10), (13, 14))
    assert [e.size for e in draft.entities] == [5, 5]
    draft.undo()
    assert len(draft.entities) == 1
    draft.redo()
    assert len(draft.entities) == 2
    draft.undo()
    draft.add("line", (1, 0), (2, 0))
    draft.redo()
    assert len(draft.entities) == 2
    assert draft.entities[-1].kind == "line"


@pytest.mark.parametrize("point", [(0, 0), (math.nan, 3), (math.inf, 1), (1_000_001, 0)])
def test_reject_invalid_geometry_without_changing_history(point):
    draft = SketchDraft()
    with pytest.raises(ValueError):
        draft.add("circle", (0, 0), point)
    assert not draft.entities


def test_circle_uses_analytic_radius():
    assert make_entity("circle", (5, 7), (8, 11)).size == 5


def test_rectangle_is_one_undoable_operation_with_shared_corners():
    from suspensionlab.model.sketch_draft import rectangle_entities

    draft = SketchDraft()
    draft.add_rectangle((10, 20), (-30, -40))
    assert len(draft.entities) == 4
    for i, entity in enumerate(draft.entities):
        assert entity.end == draft.entities[(i + 1) % 4].start
    assert rectangle_entities((10, 20), (-30, -40)) == tuple(draft.entities)
    draft.undo()
    assert draft.entities == []
    draft.redo()
    assert len(draft.entities) == 4


@pytest.mark.parametrize("point", [(0, 10), (10, 0), (float("inf"), 3), (1_000_001, 1)])
def test_rectangle_failure_does_not_mutate_or_clear_redo(point):
    draft = SketchDraft()
    draft.add("line", (0, 0), (2, 2))
    draft.undo()
    with pytest.raises(ValueError):
        draft.add_rectangle((0, 0), point)
    assert not draft.entities
    draft.redo()
    assert len(draft.entities) == 1


def test_rectangle_capacity_is_checked_before_insertion(monkeypatch):
    import suspensionlab.model.sketch_draft as model

    draft = SketchDraft()
    draft.add("line", (0, 0), (5, 5))
    monkeypatch.setattr(model, "MAX_ENTITIES", 4)
    with pytest.raises(ValueError):
        draft.add_rectangle((10, 10), (20, 20))
    assert len(draft.entities) == 1
    draft.undo()
    assert not draft.entities


def test_bounds_cover_whole_circle_and_negative_coordinates():
    from suspensionlab.model.sketch_draft import drawing_bounds

    assert drawing_bounds(()) is None
    circle = make_entity("circle", (10, 0), (13, 4))
    line = make_entity("line", (-100, -3), (-50, 2))
    assert drawing_bounds((circle, line)) == (-100, -5, 15, 5)
