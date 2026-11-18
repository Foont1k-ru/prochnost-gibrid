"""Выбор базовой плоскости на схематичном пространственном виде."""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from suspensionlab.model.sketch_plane_view import PLANES, plane_point
from suspensionlab.ui.sketch_draft_dialog import SketchDraftDialog
from suspensionlab.ui.sketch_plane_dialog import SketchPlaneDialog


@pytest.mark.parametrize("plane", PLANES)
def test_click_3d_plane_and_accept(qtbot, plane):
    dialog = SketchPlaneDialog("XY")
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.view.grab().isNull()
    point = dialog.view.to_screen(plane_point(plane, .7, .7)).toPoint()
    qtbot.mouseClick(dialog.view, Qt.MouseButton.LeftButton, pos=point)
    assert dialog.selected_plane == plane
    assert dialog.buttons[plane].isChecked()
    assert plane in dialog.selected_label.text()
    actions = dialog.findChild(QDialogButtonBox)
    qtbot.mouseClick(actions.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_choose_buttons_rotate_blank_click_and_cancel(qtbot):
    dialog = SketchPlaneDialog("XY")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.mouseClick(dialog.buttons["YZ"], Qt.MouseButton.LeftButton)
    assert dialog.selected_plane == "YZ" and not dialog.buttons["XY"].isChecked()
    qtbot.mouseClick(dialog.view, Qt.MouseButton.LeftButton, pos=dialog.view.rect().topLeft())
    assert dialog.selected_plane == "YZ"
    initial = (dialog.view.yaw, dialog.view.pitch)
    centre = dialog.view.rect().center()
    qtbot.mousePress(dialog.view, Qt.MouseButton.RightButton, pos=centre)
    qtbot.mouseMove(dialog.view, pos=centre + QPointF(50, 25).toPoint())
    qtbot.mouseRelease(dialog.view, Qt.MouseButton.RightButton, pos=centre)
    assert (dialog.view.yaw, dialog.view.pitch) != initial
    assert dialog.selected_plane == "YZ"
    actions = dialog.findChild(QDialogButtonBox)
    qtbot.mouseClick(actions.button(QDialogButtonBox.StandardButton.Cancel), Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_sketch_plane_chooser_accept_cancel_and_lock(qtbot, monkeypatch):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.plane_offset.setValue(17.5)
    def accepted(chooser):
        chooser._select("XZ")
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(SketchPlaneDialog, "exec", accepted)
    qtbot.mouseClick(dialog.choose_plane_3d, Qt.MouseButton.LeftButton)
    assert dialog.plane.currentText() == "XZ" and dialog.plane_offset.value() == 17.5
    assert dialog._document().plane == "XZ" and dialog._dirty()
    def cancelled(chooser):
        chooser._select("YZ")
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(SketchPlaneDialog, "exec", cancelled)
    qtbot.mouseClick(dialog.choose_plane_3d, Qt.MouseButton.LeftButton)
    assert dialog.plane.currentText() == "XZ"
    dialog.canvas.add_point((0, 0))
    assert not dialog.choose_plane_3d.isEnabled()
    dialog._choose_plane_in_space()
    assert dialog.plane.currentText() == "XZ"
    dialog.canvas.add_point((10, 0))
    dialog._undo()
    assert not dialog.choose_plane_3d.isEnabled()  # redo must not change the coordinate system
    dialog._saved = dialog._document()
