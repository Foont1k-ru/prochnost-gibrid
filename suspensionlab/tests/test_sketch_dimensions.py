"""Справочные размеры не управляют геометрией, но сохраняют связь с элементом."""

import json

import pytest

from suspensionlab.model.sketch_construction import fillet_lines
from suspensionlab.model.sketch_draft import Dimension, SketchDraft, make_entity
from suspensionlab.model.sketch_io import SketchDocument, SketchIOError, read_sketch, write_new_sketch


def line(a, b):
    return make_entity("line", a, b)


def test_dimensions_follow_edits_undo_and_save(tmp_path):
    draft = SketchDraft((line((0, 0), (10, 0)),))
    draft.add_dimension(0, (5, 10))
    draft.replace(0, "line", (0, 0), (25, 0))
    assert draft.entities[draft.dimensions[0].entity_index].size == 25
    draft.undo()
    assert draft.entities[0].size == 10 and len(draft.dimensions) == 1
    draft.undo()
    assert not draft.dimensions
    draft.redo()
    draft.redo()
    doc = SketchDocument("XY", 0, tuple(draft.entities), tuple(draft.dimensions))
    path = tmp_path / "dimensions.slsketch"
    write_new_sketch(path, doc)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == "3"
    assert read_sketch(path) == doc


def test_references_update_on_removal_and_split_without_silent_loss():
    draft = SketchDraft((line((0, 0), (10, 0)), line((0, 10), (10, 10))))
    draft.add_dimension(1, (5, 15))
    with pytest.raises(ValueError, match="размер"):
        draft.delete(1)
    with pytest.raises(ValueError, match="размер"):
        draft.replace_with(1, (line((0, 10), (5, 10)),))
    draft.replace_with(0, (line((0, 0), (4, 0)), line((6, 0), (10, 0))))
    assert draft.dimensions[0].entity_index == 2
    draft.undo()
    assert draft.dimensions[0].entity_index == 1
    draft.delete(0)
    assert draft.dimensions[0].entity_index == 0
    draft.undo()
    draft.delete_dimension(0)
    draft.delete(1)
    assert len(draft.entities) == 1
    draft.undo()
    draft.undo()
    assert draft.dimensions == [Dimension(1, (5, 15))]


def test_fillet_keeps_reference_and_size_tracks_shortened_line():
    first, second = line((0, 0), (100, 0)), line((0, 0), (0, 100))
    draft = SketchDraft((first, second))
    draft.add_dimension(0, (50, -10))
    draft.apply_fillet(0, 1, fillet_lines(first, second, 10))
    assert draft.dimensions[0].entity_index == 0
    assert draft.entities[0].size == pytest.approx(90)
    draft.undo()
    assert draft.entities[0].size == 100 and len(draft.dimensions) == 1


@pytest.mark.parametrize("value", [True, -1, 1, 1.5, "0"])
def test_bad_dimension_index_rejected(tmp_path, value):
    doc = SketchDocument("XY", 0, (line((0, 0), (10, 0)),), (Dimension(0, (2, 3)),))
    path = tmp_path / "bad.slsketch"
    write_new_sketch(path, doc)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["dimensions"][0]["entity_index"] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SketchIOError):
        read_sketch(path)


def test_old_versions_still_read_and_unsupported_dimension_fields_rejected(tmp_path):
    old = SketchDocument("YZ", 4, (line((0, 0), (1, 0)),))
    old_path = tmp_path / "old.slsketch"
    write_new_sketch(old_path, old)
    assert read_sketch(old_path) == old
    doc = SketchDocument("XY", 0, old.entities, (Dimension(0, (2, 3)),))
    path = tmp_path / "dimension.slsketch"
    write_new_sketch(path, doc)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = "2"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SketchIOError):
        read_sketch(path)


def test_dimension_types_and_values():
    from suspensionlab.model.sketch_draft import dimension_text

    segment = line((1, 2), (4, 6))
    draft = SketchDraft((segment, make_entity("circle", (0, 0), (5, 0)),
                         make_entity("arc", (0, 0), (5, 0), -90)))
    for index, mode, expected in ((0, "auto", "5.000 мм"), (0, "horizontal", "3.000 мм"),
                                  (0, "vertical", "4.000 мм"), (1, "diameter", "⌀ 10.000 мм"),
                                  (2, "angle", "∠ 90.000°")):
        draft.add_dimension(index, (20, 20), mode)
        assert dimension_text(draft.dimensions[-1], draft.entities[index]) == expected
    with pytest.raises(ValueError):
        draft.add_dimension(0, (1, 1), "diameter")
    with pytest.raises(ValueError):
        draft.add_dimension(1, (1, 1), "angle")


def test_mode_is_preserved_when_reference_moves(tmp_path):
    draft = SketchDraft((line((0, 0), (10, 0)), line((0, 2), (5, 2))))
    draft.add_dimension(1, (3, 4), "horizontal")
    draft.delete(0)
    assert draft.dimensions[0] == Dimension(0, (3, 4), "horizontal")
    path = tmp_path / "dimensions.slsketch"
    doc = SketchDocument("XY", 0, tuple(draft.entities), tuple(draft.dimensions))
    write_new_sketch(path, doc)
    assert read_sketch(path) == doc


def test_fillet_rectangle_remains_closed_by_preliminary_check():
    from suspensionlab.model.sketch_contours import check_contours
    from suspensionlab.model.sketch_draft import rectangle_entities

    draft = SketchDraft(rectangle_entities((0, 0), (100, 100)))
    draft.apply_fillet(0, 1, fillet_lines(draft.entities[0], draft.entities[1], 10))
    report = check_contours(tuple(draft.entities))
    assert report.total_issues == 0 and report.closed_loops == 1


@pytest.mark.parametrize("mode", [[], {}, None, 42, True, "angle"])
def test_invalid_dimension_mode_rejected_in_file(tmp_path, mode):
    doc = SketchDocument("XY", 0, (line((0, 0), (10, 0)),), (Dimension(0, (2, 3)),))
    path = tmp_path / "invalid.slsketch"
    write_new_sketch(path, doc)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["dimensions"][0]["mode"] = mode
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SketchIOError):
        read_sketch(path)
