"""Общий выбор источника не объединяет и не заменяет существующие документы."""
from copy import deepcopy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QPushButton
from test_free_arm_ui import fill

from suspensionlab.ui.main_window import MainWindow


def choose(qtbot, window, name):
    def click():
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox) and box.objectName() == 'arm_workspace_start'
        button = box.findChild(QPushButton, 'arm_workspace_' + name)
        assert button is not None and button.isVisible() and button.isEnabled()
        assert box.defaultButton() is box.findChild(QPushButton, 'arm_workspace_cancel')
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(30, click)
    window.action_arm_workspace.trigger()


def test_start_selector_cancel_both_sources_and_existing_windows(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    original_project = deepcopy(window.controller.project.to_dict())
    actions = [action for menu in window.menuBar().findChildren(QMenu) for action in menu.actions()]
    assert window.action_arm_workspace in actions
    choose(qtbot, window, 'cancel')
    assert window._free_arm_dialog is None and window._fixed_arm_skeleton_dialog is None

    def escape():
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        qtbot.keyClick(box, Qt.Key.Key_Escape)

    QTimer.singleShot(30, escape)
    window.action_arm_workspace.trigger()
    assert window._free_arm_dialog is None and window._fixed_arm_skeleton_dialog is None
    choose(qtbot, window, 'independent')
    free = window._free_arm_dialog
    assert free is not None and window._fixed_arm_skeleton_dialog is None
    fill(free)
    free.apply_fields()
    draft = free.draft
    free._fields['front_X'].setText('17')  # Unapplied input must not be replaced.
    choose(qtbot, window, 'snapshot')
    fixed = window._fixed_arm_skeleton_dialog
    assert fixed is not None and fixed.snapshot is None and window._free_arm_dialog is free
    assert free.draft is draft and free._fields['front_X'].text() == '17'
    choose(qtbot, window, 'independent')
    assert window._free_arm_dialog is free and free._fields['front_X'].text() == '17'
    choose(qtbot, window, 'snapshot')
    assert window._fixed_arm_skeleton_dialog is fixed and fixed.snapshot is None
    assert window.controller.project.to_dict() == original_project
    assert window.action_free_arm.isEnabled() and window.action_fixed_arm_skeleton.isEnabled()
    monkeypatch.setattr(free, 'confirm_close', lambda: True)
    free.close()
    fixed.close()
    assert window._free_arm_dialog is None and window._fixed_arm_skeleton_dialog is None
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.close()
