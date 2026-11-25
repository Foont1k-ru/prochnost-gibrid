"""Проверки отдельного экспериментального интерфейса снимка."""
from PySide6.QtWidgets import QMessageBox

from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def test_capture_edit_invalid_and_stale(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    controller = AppController()
    controller.project = load_template('ring')
    original = controller.project.to_dict()
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    assert dialog.snapshot is None and dialog.preview is None
    dialog._capture_snapshot()
    assert dialog.snapshot is not None and dialog.preview is not None
    anchors = dialog.preview.anchors
    start, end = anchors[0], anchors[2]
    vertex = [(start[i] + end[i]) / 2 for i in range(3)]
    vertex[2] += 50
    for field, value in zip(dialog._bend_editor.fields['front'], [*vertex, 20], strict=True):
        field.setText(str(value))
    dialog._bend_editor.checks['front'].setChecked(True)
    assert dialog.preview is not None and dialog.preview.anchors == anchors
    assert len(dialog.preview.centerlines[0]) > 2
    assert all(p.preview == dialog.preview for p in dialog._projections)
    dialog.show()
    assert not dialog._scene.grab().isNull()
    for index, projection in enumerate(dialog._projections, start=1):
        dialog._tabs.setCurrentIndex(index)
        assert not projection.grab().isNull()
    dialog._bend_editor.fields['front'][3].setText('10000')
    assert dialog.preview is None and all(p.preview is None for p in dialog._projections)
    dialog._bend_editor.fields['front'][3].setText('20')
    assert dialog.preview is not None
    point = controller.project.front.hardpoints['lbj']
    controller.move_point(point, (point.x + 10, point.y, point.z))
    assert dialog.snapshot is None and dialog.preview is None
    assert not dialog._bend_editor.checks['front'].isEnabled()
    assert controller.project.to_dict() != original
    dialog._bend_editor.checks['front'].setChecked(False)
    dialog.close()


def test_range_and_project_replacement_require_new_capture(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog._capture_snapshot()
    assert dialog.preview is not None
    dialog._spacing.setValue(5)
    assert dialog.snapshot is None and dialog.preview is None
    dialog._capture_snapshot()
    assert dialog.preview is not None
    controller.projectReplaced.emit()
    assert dialog.snapshot is None and dialog.preview is None
    dialog.close()


def test_close_with_unsaved_bend_asks(qtbot, monkeypatch):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog._capture_snapshot()
    dialog._bend_editor.checks['front'].setChecked(True)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    assert not dialog.confirm_close()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    assert dialog.confirm_close()
    dialog.close()
