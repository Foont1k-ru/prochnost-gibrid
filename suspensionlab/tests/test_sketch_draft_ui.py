"""Проверки пользовательского пробного холста."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QMessageBox

from suspensionlab.ui.sketch_draft_dialog import SketchDraftDialog


def test_mouse_points_undo_redo_and_plane_lock(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    a = canvas.to_screen((0, 0)).toPoint()
    b = canvas.to_screen((20, 10)).toPoint()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=a)
    assert canvas.pending == (0, 0)
    assert not dialog.plane.isEnabled()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=b)
    assert canvas.draft.entities[0].end == (20, 10)
    dialog._undo()
    assert not canvas.draft.entities
    assert not dialog.plane.isEnabled()  # redo must never change coordinate plane
    dialog._redo()
    assert len(canvas.draft.entities) == 1
    canvas.draft.entities.clear()


def test_exact_input_cancel_and_close_warning(qtbot, monkeypatch):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.canvas.add_point((1.234, -2.345))
    dialog.canvas.add_point((4.567, 5.678))
    assert dialog.canvas.draft.entities[0].start == (1.234, -2.345)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not dialog.close()
    assert dialog.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    assert dialog.close()


def test_screen_mapping_and_grid(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    point = (13.0, -17.0)
    assert canvas.to_world(canvas.to_screen(point), snap=False) == point
    assert canvas.to_world(canvas.to_screen(point)) == (10, -20)
    canvas.hover = (10, -20)
    canvas.pending = (0, 0)
    canvas.repaint()
    assert canvas.to_world(QPointF(canvas.width() / 2, canvas.height() / 2)) == (0, 0)
    canvas.pending = None


def test_selection_delete_undo_and_point_snap(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    canvas.add_point((2, 3))
    canvas.add_point((42, 3))
    # An endpoint wins over the grid when close enough in screen pixels.
    assert canvas.mouse_point(canvas.to_screen((2.5, 3))) == (2, 3)
    assert canvas.snap_label == "точка"
    dialog.tool.setCurrentIndex(2)
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((22, 3)).toPoint())
    assert canvas.selected == 0
    assert dialog.edit_button.isEnabled()
    dialog._delete()
    assert not canvas.draft.entities
    dialog._undo()
    assert len(canvas.draft.entities) == 1
    dialog._saved = dialog._document()


def test_save_open_and_dirty_warning(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.plane.setCurrentText("XZ")
    dialog.plane_offset.setValue(12.125)
    dialog.canvas.add_point((1, 2))
    dialog.canvas.add_point((30, 40))
    path = tmp_path / "sketch.slsketch"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    assert dialog._save()
    assert not dialog._dirty()
    dialog.canvas.add_point((50, 60))
    dialog.canvas.add_point((70, 80))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    dialog._new()
    assert len(dialog.canvas.draft.entities) == 2
    # Discard is confirmed, failed open must still not replace the document.
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    bad = tmp_path / "bad.slsketch"
    bad.write_text("invalid")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(bad), ""))
    dialog._open()
    assert len(dialog.canvas.draft.entities) == 2 and dialog._dirty()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    dialog._open()
    assert dialog.plane.currentText() == "XZ" and dialog.plane_offset.value() == 12.125
    assert len(dialog.canvas.draft.entities) == 1 and not dialog._dirty()
    assert not dialog.plane.isEnabled()


def test_circle_editor_and_invalid_radius(qtbot):
    from suspensionlab.model.sketch_draft import make_entity
    from suspensionlab.ui.sketch_draft_dialog import EntityEditor

    parent = SketchDraftDialog()
    qtbot.addWidget(parent)
    editor = EntityEditor(make_entity("circle", (5, 6), (8, 10)), parent)
    qtbot.addWidget(editor)
    editor.values[0].setValue(10)
    editor.values[2].setValue(10)
    result = editor.result_entity()
    assert result.start == (10, 6)
    assert result.size == 10
    editor.values[2].setValue(0)
    import pytest

    with pytest.raises(ValueError):
        editor.result_entity()
