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
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    assert not dialog.close()
    assert dialog.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
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
