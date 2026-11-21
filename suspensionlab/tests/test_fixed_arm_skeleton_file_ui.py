"""Сохранение и восстановление окна без незаметного изменения проекта."""
from PySide6.QtWidgets import QFileDialog, QMessageBox

from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def test_save_and_open_recalculate_and_restore_controls(qtbot, monkeypatch, tmp_path):
    controller = AppController()
    controller.project = load_template('ring')
    original = controller.project.to_dict()
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog._capture_snapshot()
    anchors = dialog.preview.anchors
    start, end = anchors[0], anchors[2]
    vertex = [(start[i] + end[i]) / 2 for i in range(3)]
    vertex[2] += 50
    for field, value in zip(dialog._bend_editor.fields['front'], [*vertex, 20], strict=True):
        field.setText(str(value))
    dialog._bend_editor.checks['front'].setChecked(True)
    preview = dialog.preview
    path = tmp_path / 'arm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    path = tmp_path / 'arm.slarm'
    assert path.is_file() and dialog.confirm_close()
    dialog._radius.setValue(14)
    assert dialog._radius.value() == 14 and dialog._state() != dialog._saved_state
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert dialog.preview == preview and dialog.snapshot is not None
    assert dialog._radius.value() == 12 and dialog._bend_editor.values()['front']['vertex_mm'] == vertex
    assert dialog.confirm_close() and controller.project.to_dict() == original
    dialog.close()


def test_failed_open_keeps_existing_preview_and_controls(qtbot, monkeypatch, tmp_path):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog._capture_snapshot()
    before = dialog._state(), dialog.preview
    invalid = tmp_path / 'bad.slarm'
    invalid.write_text('{bad json', encoding='utf-8')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(invalid), ''))
    dialog._open_file()
    assert warnings and (dialog._state(), dialog.preview) == before
    dialog.close()


def test_save_race_and_existing_file_never_overwrite(qtbot, monkeypatch, tmp_path):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog._capture_snapshot()
    target = tmp_path / 'existing.slarm'
    target.write_bytes(b'original')
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    dialog._save_file()
    assert warnings and target.read_bytes() == b'original'
    new = tmp_path / 'new.slarm'
    def change_during_dialog(*args):
        point = controller.project.front.hardpoints['lbj']
        point.x += 1  # also catch an unsignalled edit
        return str(new), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', change_during_dialog)
    dialog._save_file()
    assert len(warnings) == 2 and not new.exists() and dialog.preview is None
    dialog.close()


def test_main_menu_and_unsaved_close(qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    from suspensionlab.ui.main_window import MainWindow

    controller = AppController()
    controller.project = load_template('ring')
    window = MainWindow(controller, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    window.show()
    window.action_fixed_arm_skeleton.trigger()
    dialog = window._fixed_arm_skeleton_dialog
    assert dialog is not None and dialog.isVisible()
    dialog._capture_snapshot()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    assert not dialog.confirm_close()
    assert not window.close()
    assert window.isVisible()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    assert window.close()
