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
    window._confirm_discard_changes = lambda: True
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


def test_manual_save_never_targets_shared_autosave_even_if_approved(qtbot, tmp_path, monkeypatch):
    import os

    import pytest

    from suspensionlab.model.project_io import ProjectIOError
    from suspensionlab.ui import controller as module

    backup = tmp_path / 'autosave.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    c = AppController()
    c.set_value(c.project.vehicle, 'mass_kg', 1777.)
    # Protection applies even before the shared file exists and before suffix expansion.
    with pytest.raises(ProjectIOError) as err:
        c.save_project(tmp_path / 'autosave.json')
    assert err.value.message_key == 'autosave.protected'
    assert not backup.exists() and c.dirty and c.project.path is None
    assert c.autosave()
    original = backup.read_bytes()
    candidates = [backup, tmp_path / 'autosave.json']
    symlink = tmp_path / 'alias.susp.json'
    try:
        symlink.symlink_to(backup)
    except OSError:
        pass
    else:
        candidates.append(symlink)
    hardlink = tmp_path / 'hard.susp.json'
    try:
        os.link(backup, hardlink)
    except OSError:
        pass
    else:
        candidates.append(hardlink)
    for candidate in candidates:
        with pytest.raises(ProjectIOError) as err:
            c.save_project(candidate)
        assert err.value.message_key == 'autosave.protected'
        assert c.dirty and c.project.path is None and backup.read_bytes() == original
    # Manual save to a separate project works; automatic save keeps working.
    ordinary = c.save_project(tmp_path / 'real_project')
    assert load_project(ordinary).vehicle.mass_kg == 1777.
    c.set_value(c.project.vehicle, 'mass_kg', 1888.)
    assert c.autosave() and load_project(backup).vehicle.mass_kg == 1888.


def test_opening_shared_copy_normally_requires_save_as(qtbot, tmp_path, monkeypatch):
    import pytest

    from suspensionlab.model.project_io import ProjectIOError
    from suspensionlab.ui import controller as module

    backup = tmp_path / 'autosave.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    c = AppController()
    save_project(c.project, backup)
    before = backup.read_bytes()
    c.open_project(backup)
    c.set_value(c.project.vehicle, 'mass_kg', 1900.)
    with pytest.raises(ProjectIOError) as err:
        c.save_project()
    assert err.value.message_key == 'autosave.protected'
    assert c.project.path == str(backup) and c.dirty and backup.read_bytes() == before
    path = c.save_project(tmp_path / 'new_copy')
    assert load_project(path).vehicle.mass_kg == 1900.
    assert backup.read_bytes() == before and not c.dirty


def test_manual_save_fails_closed_if_autosave_path_cannot_be_checked(qtbot, tmp_path, monkeypatch):
    import pytest

    from suspensionlab.model.project_io import ProjectIOError
    from suspensionlab.ui import controller as module

    c = AppController()
    c.set_value(c.project.vehicle, 'mass_kg', 1800.)
    monkeypatch.setattr(module, 'autosave_path', lambda: (_ for _ in ()).throw(OSError('inaccessible')))
    path = tmp_path / 'project.susp.json'
    with pytest.raises(ProjectIOError):
        c.save_project(path)
    assert c.dirty and c.project.path is None and not path.exists()


def test_save_as_ui_refuses_autosave_and_accepts_separate_file(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from suspensionlab.ui import controller as module

    backup = tmp_path / 'autosave.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    c = AppController()
    save_project(c.project, backup)
    before = backup.read_bytes()
    c.open_project(backup)
    c.set_value(c.project.vehicle, 'mass_kg', 1910.)
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    errors = []
    monkeypatch.setattr(window, '_show_error', errors.append)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(backup), ''))
    assert not window._save_project_as()
    assert errors[-1].message_key == 'autosave.protected' and backup.read_bytes() == before
    assert c.dirty and c.project.path == str(backup)
    new = tmp_path / 'normal.susp.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(new), ''))
    assert window._save_project_as()
    assert load_project(new).vehicle.mass_kg == 1910. and not c.dirty
    assert backup.read_bytes() == before


def test_busy_autosave_preserves_data_and_retries_after_lock_release(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.autosave_guard import autosave_write_lock
    from suspensionlab.ui import controller as module

    backup = tmp_path / 'autosave.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    c = AppController()
    c.set_value(c.project.vehicle, 'mass_kg', 1850.)
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    messages = []
    c.statusMessage.connect(messages.append)
    with autosave_write_lock(backup):
        assert not c.autosave() and c.autosave_waiting and c.autosave_busy
        assert not backup.exists() and c.dirty and c.project.path is None
        assert messages[-1] == 'autosave.busy'
        assert 'другой экземпляр' in window._status_autosave.toolTip()
    assert c.autosave() and not c.autosave_busy and not c.autosave_waiting
    assert c.dirty and load_project(backup).vehicle.mass_kg == 1850.


def test_two_approved_instances_cannot_silently_replace_changed_copy(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import controller as module

    backup = tmp_path / 'autosave.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    source = AppController()
    assert source.autosave()
    a, b = AppController(), AppController()
    for c in (a, b):
        stamp = c.prepare_autosave_overwrite()
        assert stamp is not None
        c.allow_autosave_overwrite(stamp)
    a.set_value(a.project.vehicle, 'mass_kg', 1730.)
    b.set_value(b.project.vehicle, 'mass_kg', 1830.)
    assert a.autosave()
    first = backup.read_bytes()
    assert not b.autosave() and b.autosave_waiting and not b.autosave_busy
    assert backup.read_bytes() == first and load_project(backup).vehicle.mass_kg == 1730.
