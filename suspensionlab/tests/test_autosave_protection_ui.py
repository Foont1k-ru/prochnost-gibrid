from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from suspensionlab.model.project_io import load_project, save_project
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow


def test_previous_session_requires_explicit_approval_and_blocks_changed_copy(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import controller as module

    backup = tmp_path / 'autosave.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    first = AppController()
    assert first.autosave()
    prior = backup.read_bytes()
    controller = AppController()
    window = MainWindow(controller, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    assert controller.autosave_waiting and 'приостановлено' in window.windowTitle()
    controller.set_value(controller.project.vehicle, 'mass_kg', 1777.)
    assert not controller.autosave() and backup.read_bytes() == prior
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    window._allow_autosave_overwrite()
    assert controller.autosave_waiting and backup.read_bytes() == prior
    def tamper(*args):
        backup.write_bytes(b'external')
        return QMessageBox.StandardButton.Yes
    warnings = []
    monkeypatch.setattr(QMessageBox, 'question', tamper)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    window._allow_autosave_overwrite()
    assert warnings and controller.autosave_waiting and backup.read_bytes() == b'external'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    window._allow_autosave_overwrite()
    assert not controller.autosave_waiting and backup.read_bytes() == b'external'
    assert controller.autosave() and load_project(backup).vehicle.mass_kg == 1777.
    # Approval is scoped to last written content, not an unconditional unlock.
    backup.write_bytes(b'changed again')
    assert not controller.autosave() and controller.autosave_waiting
    assert backup.read_bytes() == b'changed again'


def test_recovered_copy_remains_protected_after_saving_new_file(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import controller as module

    backup = tmp_path / 'autosave.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    source = AppController()
    save_project(source.project, backup)
    before = backup.read_bytes()
    c = AppController()
    assert c.check_autosave_protection()
    project, path = c.read_autosave()
    c.recover_autosave(project, path)
    c.save_project(tmp_path / 'recovered')
    assert not c.recovery_pending and c.autosave_waiting
    c.set_value(c.project.vehicle, 'mass_kg', 1800.)
    assert not c.autosave() and backup.read_bytes() == before
    expected = c.prepare_autosave_overwrite()
    assert expected is not None
    c.allow_autosave_overwrite(expected)
    assert c.autosave() and load_project(backup).vehicle.mass_kg == 1800.
