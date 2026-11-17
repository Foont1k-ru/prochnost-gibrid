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
