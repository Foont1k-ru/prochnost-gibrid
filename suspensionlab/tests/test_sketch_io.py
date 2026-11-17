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
    lambda d: d.update(version="2"), lambda d: d.update(units="in"),
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
