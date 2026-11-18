"""Ошибки файла проекта не подменяют работу пользователя или копии."""

import pytest
from PySide6.QtCore import QSettings

from suspensionlab.model.project_io import ProjectIOError
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow


def test_failed_open_keeps_current_project_and_undo(qtbot, tmp_path):
    c = AppController()
    c.set_value(c.project.vehicle, 'mass_kg', 1777.)
    original = c.project
    invalid = tmp_path / 'invalid.susp.json'
    invalid.write_text('{"schema_version":"1.0","vehicle":{"mass_kg":NaN}}', encoding='utf-8')
    with pytest.raises(ProjectIOError) as error:
        c.open_project(invalid)
    assert error.value.message_key == 'error.project.invalid_json_values'
    assert c.project is original and c.dirty and c.project.vehicle.mass_kg == 1777.
    c.undo.undo()
    assert c.project.vehicle.mass_kg != 1777.


def test_invalid_current_model_never_overwrites_manual_or_automatic_copy(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import controller as module

    backup = tmp_path / 'autosave.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    c = AppController()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    target = c.save_project(tmp_path / 'project')
    assert c.autosave()
    old_project, old_autosave = target.read_bytes(), backup.read_bytes()
    c.set_value(c.project.vehicle, 'mass_kg', 1700.)
    # Simulate invalid data introduced outside normal UI numeric controls.
    c.project.vehicle.mass_kg = float('nan')
    errors = []
    monkeypatch.setattr(window, '_show_error', lambda error: errors.append(error.message_key))
    assert not window._save_project()
    assert errors == ['error.project.invalid_save']
    assert c.dirty and c.project.path == str(target)
    assert target.read_bytes() == old_project
    assert not c.autosave() and c.autosave_waiting
    assert backup.read_bytes() == old_autosave
    c.project.vehicle.mass_kg = 1700.
    assert c.autosave()
    assert window._save_project() and not c.dirty


def test_oversize_project_does_not_replace_open_project_or_saved_files(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model import project_io
    from suspensionlab.ui import controller as module

    backup = tmp_path / 'autosave.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    c = AppController()
    target = c.save_project(tmp_path / 'project')
    assert c.autosave()
    manual_before, auto_before = target.read_bytes(), backup.read_bytes()
    c.set_value(c.project.vehicle, 'mass_kg', 1777.)
    current_project = c.project
    monkeypatch.setattr(project_io, 'MAX_PROJECT_BYTES', 50)
    with pytest.raises(ProjectIOError) as error:
        c.open_project(target)
    assert error.value.message_key == 'error.project.too_large'
    assert c.project is current_project and c.dirty and c.project.vehicle.mass_kg == 1777.
    with pytest.raises(ProjectIOError) as error:
        c.save_project()
    assert error.value.message_key == 'error.project.too_large'
    assert c.project.path == str(target) and c.dirty
    assert not c.autosave() and c.autosave_waiting
    assert target.read_bytes() == manual_before and backup.read_bytes() == auto_before
