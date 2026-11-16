"""Глобальные настройки приближённой сетки STEP, без изменений проекта."""
from threading import Event

import numpy as np
import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QDialog, QMessageBox

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_transport import CadJob, CadPreviewError
from suspensionlab.ui.cad_preview_dialog import CadPreviewDialog
from suspensionlab.ui.cad_preview_settings import CAD_DEVIATION_KEY, CadPreviewSettingsDialog, read_cad_deviation
from suspensionlab.ui.main_window import MainWindow


def test_settings_menu_presets_cancel_and_persistence(qtbot, tmp_path):
    filename = tmp_path / "settings.ini"
    settings = QSettings(str(filename), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    original = window.controller.project.to_dict()
    assert any(action.text() == "Настройки" for action in window.menuBar().actions())
    assert window.action_cad_settings.isEnabled()
    checked = []

    def setup_dialog():
        dialog = window.findChild(CadPreviewSettingsDialog)
        assert dialog is not None
        try:
            assert dialog._quality.currentData() == dialog._deviation.value() == 10.
            dialog._quality.setCurrentIndex(dialog._quality.findData(2.0))
            assert dialog._deviation.value() == 2.
            dialog._deviation.setValue(3.7)
            assert dialog._quality.currentData() is None
            dialog.accept()
            checked.append(True)
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(0, setup_dialog)
    window.action_cad_settings.trigger()
    assert checked == [True]
    settings2 = QSettings(str(filename), QSettings.Format.IniFormat)
    assert read_cad_deviation(settings2) == 3.7
    new_view = CadPreviewDialog(window, settings=settings2)
    qtbot.addWidget(new_view)
    assert new_view._selected_deviation == 3.7
    edit = CadPreviewSettingsDialog(settings2)
    qtbot.addWidget(edit)
    assert edit._deviation.value() == 3.7 and edit._quality.currentData() is None
    edit._quality.setCurrentIndex(edit._quality.findData(0.2))
    assert edit._deviation.value() == 0.2
    edit.reject()
    assert read_cad_deviation(settings2) == 3.7
    assert window.controller.project.to_dict() == original


def test_preview_settings_apply_automatically_after_change(qtbot, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    mesh = CadMesh(np.array([[[0, 0, 0], [10, 0, 0], [0, 10, 0]]]), 1)
    calls = []

    def load(_self, path, deviation):
        calls.append((path, deviation))
        return mesh

    monkeypatch.setattr(CadJob, "run", load)
    dialog = CadPreviewDialog(settings=settings)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._selected_deviation == 10. and "для чтения" in dialog._quality_status.text()
    path = tmp_path / "model.step"
    dialog.load_file(path)
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    assert calls == [(path, 10.)] and dialog._view.mesh is mesh
    dialog._add_measurement_point((1, 2, 3))
    changed = []

    def change_settings():
        preferences = dialog.findChild(CadPreviewSettingsDialog)
        assert preferences is not None
        try:
            preferences._quality.setCurrentIndex(preferences._quality.findData(0.2))
            preferences.accept()
            changed.append(True)
        finally:
            if preferences.isVisible():
                preferences.reject()

    QTimer.singleShot(0, change_settings)
    dialog._quality_settings.click()
    assert changed == [True] and dialog._selected_deviation == 0.2
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    assert calls[-1] == (path, 0.2) and dialog._view.mesh is mesh
    assert not dialog._measurement_points and "0.2 мм" in dialog._quality_status.text()
    assert "Перестроить" not in dialog._quality_status.text()


def test_quality_disabled_during_job_and_failed_reload_does_not_claim_applied(qtbot, tmp_path, monkeypatch):
    started, release = Event(), Event()

    def slow_job(_self, path, deviation):
        started.set()
        assert release.wait(10)
        raise CadPreviewError("limit")

    monkeypatch.setattr(CadJob, "run", slow_job)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue(CAD_DEVIATION_KEY, 0.2)
    dialog = CadPreviewDialog(settings=settings)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.load_file(tmp_path / "model.step")
    assert started.wait(5)
    try:
        assert not dialog._quality_settings.isEnabled()
    finally:
        release.set()
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    assert dialog._quality_settings.isEnabled()
    assert dialog._view.mesh is None and dialog._loaded_deviation is None
    assert "для чтения" in dialog._quality_status.text()
    assert "ограничения" in dialog._status.text()


@pytest.mark.parametrize("raw", ["nan", "inf", "bad", -1, 0.1, 20.1, 1.23, True, [], None])
def test_invalid_settings_fall_back_without_mutating_input(tmp_path, raw):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue(CAD_DEVIATION_KEY, raw)
    assert read_cad_deviation(settings) == 10.
    assert settings.value(CAD_DEVIATION_KEY) == raw


def test_save_failure_keeps_settings_dialog_open(qtbot, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path), QSettings.Format.IniFormat)  # Каталог вместо файла.
    dialog = CadPreviewSettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._deviation.setValue(2.)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog.accept()
    assert warnings and dialog.isVisible() and dialog.result() != QDialog.DialogCode.Accepted
    assert read_cad_deviation(settings) == 10.


def test_preview_cancel_settings_retains_applied_and_saved_value(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    view = CadPreviewDialog(settings=settings)
    qtbot.addWidget(view)
    view.show()
    view._show_mesh(CadMesh(np.array([[[0, 0, 0], [10, 0, 0], [0, 10, 0]]]), 1))
    seen = []

    def cancel():
        edit = QApplication.activeModalWidget()
        assert isinstance(edit, CadPreviewSettingsDialog)
        edit._deviation.setValue(2)
        edit.reject()
        seen.append(True)

    QTimer.singleShot(0, cancel)
    view._quality_settings.click()
    assert seen == [True] and view._selected_deviation == 10 and read_cad_deviation(settings) == 10
    assert view._loaded_deviation == 10 and "Перестроить" not in view._quality_status.text()


def test_quality_keeps_old_mesh_during_reload_and_on_cancel(qtbot, tmp_path, monkeypatch):
    started, release = Event(), Event()
    old = CadMesh(np.array([[[0, 0, 0], [10, 0, 0], [0, 10, 0]]]), 1)
    new = CadMesh(np.array([[[0, 0, 0], [20, 0, 0], [0, 20, 0]]]), 1)
    def load(_self, path, deviation):
        if deviation == 10.:
            return old
        started.set()
        assert release.wait(10)
        return new
    monkeypatch.setattr(CadJob, "run", load)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    view = CadPreviewDialog(settings=settings)
    qtbot.addWidget(view)
    view.show()
    path = tmp_path / "model.step"
    view.load_file(path)
    qtbot.waitUntil(lambda: view._reader is None, timeout=10000)
    view._add_measurement_point((1, 2, 3))
    view._selected_deviation = 0.2
    view.load_file(path)
    assert started.wait(5)
    try:
        assert view._view.mesh is old and view._measurement_points
        assert view._progress_bar.isVisible()
        view._update_progress("faces", 234)
        assert "234" in view._progress_label.text()
        view._cancel_read()
    finally:
        release.set()
    qtbot.waitUntil(lambda: view._reader is None, timeout=10000)
    assert view._view.mesh is old and view._loaded_deviation == 10.
    assert view._measurement_points and "отменено" in view._status.text().lower()
    assert not view._progress_bar.isVisible()


def test_failed_quality_reload_keeps_old_model(qtbot, tmp_path, monkeypatch):
    mesh = CadMesh(np.array([[[0, 0, 0], [10, 0, 0], [0, 10, 0]]]), 1)
    def load(_self, path, deviation):
        if deviation == 2.:
            raise CadPreviewError("memory")
        return mesh
    monkeypatch.setattr(CadJob, "run", load)
    view = CadPreviewDialog(settings=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(view)
    view.load_file(tmp_path / "one.step")
    qtbot.waitUntil(lambda: view._reader is None, timeout=10000)
    view._selected_deviation = 2.
    view.load_file(tmp_path / "one.step")
    qtbot.waitUntil(lambda: view._reader is None, timeout=10000)
    assert view._view.mesh is mesh and view._loaded_deviation == 10.
    assert "прежняя" in view._status.text() and "512" in view._status.text()
