"""Отдельный формат: строгая проверка и сохранение без перезаписи."""

import json
import os
from dataclasses import replace

import pytest

from suspensionlab.model.sketch_draft import SketchDraft, make_entity
from suspensionlab.model.sketch_io import SketchDocument, SketchIOError, read_sketch, write_new_sketch


def document():
    return SketchDocument("XZ", 17.125, (make_entity("line", (1.2, 2.5), (3, 4)),
                                         make_entity("circle", (10, 20), (13, 24))))


def test_round_trip_and_no_overwrite(tmp_path):
    path = tmp_path / "example.slsketch"
    write_new_sketch(path, document())
    saved = path.read_bytes()
    assert read_sketch(path) == document()
    with pytest.raises(SketchIOError):
        write_new_sketch(path, replace(document(), plane="XY"))
    assert path.read_bytes() == saved
    assert not list(tmp_path.glob(".sketch-*.tmp"))


def test_wrong_suffix_and_existing_project_are_safe(tmp_path):
    target = tmp_path / "myproject.json"
    target.write_text("original")
    with pytest.raises(SketchIOError):
        write_new_sketch(target, document())
    assert target.read_text() == "original"
    with pytest.raises(SketchIOError):
        read_sketch(target)


def test_symlink_destination_not_overwritten(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("original")
    link = tmp_path / "link.slsketch"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available")
    with pytest.raises(SketchIOError):
        write_new_sketch(link, document())
    assert link.is_symlink() and target.read_text() == "original"


@pytest.mark.parametrize("change", [
    lambda d: d.update(version="99"), lambda d: d.update(units="in"),
    lambda d: d.update(plane="AA"), lambda d: d.update(offset_mm=True),
    lambda d: d.update(offset_mm=0.00001), lambda d: d.update(extra="unexpected"),
    lambda d: d["entities"][0].update(start=[float("nan"), 1]),
    lambda d: d["entities"][0].update(end=d["entities"][0]["start"]),
    lambda d: d["entities"][0].update(kind="polyline"),
])
def test_reject_corrupt_documents(tmp_path, change):
    path = tmp_path / "corrupt.slsketch"
    original = tmp_path / "valid.slsketch"
    write_new_sketch(original, document())
    data = json.loads(original.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SketchIOError):
        read_sketch(path)


def test_duplicate_keys_and_oversize(tmp_path):
    path = tmp_path / "bad.slsketch"
    path.write_text('{"version":"1","version":"2"}')
    with pytest.raises(SketchIOError):
        read_sketch(path)
    path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    with pytest.raises(SketchIOError):
        read_sketch(path)


def test_fifo_is_not_blocking(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unsupported")
    path = tmp_path / "pipe.slsketch"
    os.mkfifo(path)
    with pytest.raises(SketchIOError):
        read_sketch(path)


def test_edits_and_delete_participate_in_undo_redo():
    draft = SketchDraft(document().entities)
    draft.replace(0, "line", (0, 0), (1, 1))
    draft.delete(1)
    assert len(draft.entities) == 1
    draft.undo()
    assert len(draft.entities) == 2
    draft.undo()
    assert tuple(draft.entities) == document().entities
    draft.redo()
    assert draft.entities[0].start == (0, 0)
    with pytest.raises(ValueError):
        draft.replace(0, "line", (0, 0), (0, 0))
    draft.redo()
    assert len(draft.entities) == 1


def test_collision_created_during_save_is_never_replaced(tmp_path, monkeypatch):
    import suspensionlab.model.sketch_io as sketch_io

    path = tmp_path / "race.slsketch"
    link = sketch_io.os.link

    def collide(source, destination):
        path.write_text("someone else")
        link(source, destination)

    monkeypatch.setattr(sketch_io.os, "link", collide)
    with pytest.raises(SketchIOError):
        write_new_sketch(path, document())
    assert path.read_text() == "someone else"
    assert not list(tmp_path.glob(".sketch-*.tmp"))


def test_version_two_arc_roundtrip_and_old_reader_guard(tmp_path):
    arc = make_entity("arc", (0, 0), (10, 0), -90)
    doc = SketchDocument("XY", 0, (arc,))
    path = tmp_path / "arc.slsketch"
    write_new_sketch(path, doc)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == "2" and data["entities"][0]["sweep_deg"] == -90
    assert read_sketch(path) == doc
    data["version"] = "1"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SketchIOError):
        read_sketch(path)


def extrusion_document():
    from suspensionlab.model.sketch_draft import rectangle_entities
    from suspensionlab.model.sketch_extrude_settings import ExtrusionSettings

    entities = (*rectangle_entities((0, 0), (100, 50)),
                make_entity("circle", (25, 25), (30, 25)),
                *rectangle_entities((50, 15), (70, 35)))
    settings = ExtrusionSettings("symmetric", 1.25, "negative", ((4, 0., "positive"), (5, 3., "auto")))
    return SketchDocument("XZ", 5, entities, (), settings)


def test_extrusion_settings_version_six_roundtrip_and_legacy_defaults(tmp_path):
    from suspensionlab.model.sketch_extrude_settings import ExtrusionSettings

    target = tmp_path / "settings.slsketch"
    write_new_sketch(target, extrusion_document())
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["version"] == "6" and data["dimensions"] == []
    assert read_sketch(target) == extrusion_document()
    legacy = tmp_path / "legacy.slsketch"
    write_new_sketch(legacy, document())
    assert json.loads(legacy.read_text(encoding="utf-8"))["version"] == "1"
    assert read_sketch(legacy).extrusion == ExtrusionSettings()


@pytest.mark.parametrize("change", [
    lambda e: e.update(direction="bad"),
    lambda e: e.update(hole_side="bad"),
    lambda e: e.update(hole_depth=True),
    lambda e: e.update(hole_depth=-1),
    lambda e: e.update(hole_depth=0.0001),
    lambda e: e.update(hole_depth=1_000_001),
    lambda e: e.update(unexpected=1),
    lambda e: e["hole_overrides"][0].update(entity_index=True),
    lambda e: e["hole_overrides"][0].update(entity_index=99),
    lambda e: e["hole_overrides"][1].update(entity_index=6),  # not canonical contour index
    lambda e: e["hole_overrides"][1].update(entity_index=4),
    lambda e: e["hole_overrides"][0].update(depth=-1),
    lambda e: e["hole_overrides"][0].update(side="bad"),
    lambda e: e["hole_overrides"].reverse(),
])
def test_reject_corrupt_persisted_extrusion_settings(tmp_path, change):
    good, bad = tmp_path / "good.slsketch", tmp_path / "bad.slsketch"
    write_new_sketch(good, extrusion_document())
    data = json.loads(good.read_text(encoding="utf-8"))
    change(data["extrusion"])
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SketchIOError):
        read_sketch(bad)


def test_reject_stale_overrides_when_geometry_is_open(tmp_path):
    from suspensionlab.model.sketch_extrude_settings import ExtrusionSettings

    doc = replace(extrusion_document(), entities=extrusion_document().entities[:-1],
                  extrusion=ExtrusionSettings(hole_overrides=((4, 2., "auto"),)))
    with pytest.raises(SketchIOError):
        write_new_sketch(tmp_path / "bad.slsketch", doc)


def test_version_six_keeps_arcs_and_both_angle_dimensions(tmp_path):
    from suspensionlab.model.sketch_draft import Dimension
    from suspensionlab.model.sketch_extrude_settings import ExtrusionSettings

    line_a = make_entity("line", (0, 0), (10, 0))
    line_b = make_entity("line", (0, 0), (0, 10))
    arc = make_entity("arc", (30, 30), (35, 30), 90)
    dimensions = (Dimension(0, (4, 4), "inclination"), Dimension(0, (5, 5), "between", 1))
    doc = SketchDocument("YZ", 1, (line_a, line_b, arc), dimensions, ExtrusionSettings(direction="negative"))
    path = tmp_path / "angles.slsketch"
    write_new_sketch(path, doc)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == "6"
    assert read_sketch(path) == doc


@pytest.mark.parametrize("thickness", [0.001, 8.125, 1_000_000])
def test_thickness_version_seven_roundtrip(tmp_path, thickness):
    doc = extrusion_document()
    doc = replace(doc, extrusion=replace(doc.extrusion, thickness_mm=thickness))
    path = tmp_path / "thickness.slsketch"
    write_new_sketch(path, doc)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == "7" and data["extrusion"]["thickness_mm"] == thickness
    assert read_sketch(path) == doc


def test_v6_restores_thickness_default_and_old_versions_remain_unchanged(tmp_path):
    doc = extrusion_document()
    path = tmp_path / "v6.slsketch"
    write_new_sketch(path, doc)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == "6" and "thickness_mm" not in data["extrusion"]
    assert read_sketch(path).extrusion.thickness_mm == 10
    # A version 6 file cannot silently contain a version 7 field.
    data["extrusion"]["thickness_mm"] = 12
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SketchIOError):
        read_sketch(path)


@pytest.mark.parametrize("bad", [0, -1, 0.0001, 2.0001, 1_000_001, True, None, "4", float("nan"), float("inf")])
def test_version_seven_rejects_invalid_thickness(tmp_path, bad):
    doc = extrusion_document()
    doc = replace(doc, extrusion=replace(doc.extrusion, thickness_mm=12))
    path = tmp_path / "bad.slsketch"
    write_new_sketch(path, doc)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["extrusion"]["thickness_mm"] = bad
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SketchIOError):
        read_sketch(path)


def test_version_seven_rejects_missing_thickness(tmp_path):
    doc = extrusion_document()
    path = tmp_path / "missing.slsketch"
    write_new_sketch(path, replace(doc, extrusion=replace(doc.extrusion, thickness_mm=12)))
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["extrusion"]["thickness_mm"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SketchIOError):
        read_sketch(path)
