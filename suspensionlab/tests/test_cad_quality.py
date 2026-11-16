"""Настройки приближения сетки — только для экспериментального STEP-просмотра."""
from threading import Event

import numpy as np
from PySide6.QtCore import QSettings

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_transport import CadJob, CadPreviewError
from suspensionlab.ui.cad_preview_dialog import CadPreviewDialog
from suspensionlab.ui.main_window import MainWindow


def test_quality_presets_manual_and_rebuild_are_explicit(qtbot, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    window.controller.new_project("ring")
    original_project = window.controller.project.to_dict()
    mesh = CadMesh(np.array([[[0, 0, 0], [10, 0, 0], [0, 10, 0]]]), 1)
    calls = []

    def load(_self, path, deviation):
        calls.append((path, deviation))
        return mesh

    monkeypatch.setattr(CadJob, "run", load)
    dialog = CadPreviewDialog(window)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._quality.currentData() == dialog._deviation.value() == 10
    assert "для чтения" in dialog._quality_status.text()
    dialog._quality.setCurrentIndex(dialog._quality.findData(2.0))
    assert dialog._deviation.value() == 2
    path = tmp_path / "model.step"
    dialog.load_file(path)
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    assert calls == [(path, 2)] and dialog._view.mesh is mesh
    assert "Показана сетка" in dialog._quality_status.text() and "2.0 мм" in dialog._quality_status.text()
    dialog._add_measurement_point((1, 2, 3))
    dialog._quality.setCurrentIndex(dialog._quality.findData(0.2))
    assert dialog._deviation.value() == 0.2 and len(calls) == 1
    assert dialog._view.mesh is mesh and dialog._measurement_points == [(1, 2, 3)]
    assert "2.0 мм" in dialog._quality_status.text() and "0.2 мм" in dialog._quality_status.text()
    assert "Перестроить" in dialog._quality_status.text()
    dialog._deviation.setValue(3.7)
    assert dialog._quality.currentData() is None and dialog._deviation.value() == 3.7
    dialog._deviation.setValue(2.)
    assert dialog._quality.currentData() == 2. and "Перестроить" not in dialog._quality_status.text()
    dialog._quality.setCurrentIndex(dialog._quality.findData(0.2))
    dialog._reload.click()
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    assert calls[-1] == (path, 0.2) and dialog._view.mesh is mesh
    assert not dialog._measurement_points and "0.2 мм" in dialog._quality_status.text()
    assert "Перестроить" not in dialog._quality_status.text()
    assert window.controller.project.to_dict() == original_project
    window.controller.dirty = False


def test_quality_disabled_during_job_and_failed_reload_does_not_claim_applied(qtbot, tmp_path, monkeypatch):
    started, release = Event(), Event()

    def slow_job(_self, path, deviation):
        started.set()
        assert release.wait(10)
        raise CadPreviewError("limit")

    monkeypatch.setattr(CadJob, "run", slow_job)
    dialog = CadPreviewDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._quality.setCurrentIndex(dialog._quality.findData(0.2))
    dialog.load_file(tmp_path / "model.step")
    assert started.wait(5)
    assert not dialog._quality.isEnabled() and not dialog._deviation.isEnabled()
    release.set()
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    assert dialog._quality.isEnabled() and dialog._deviation.isEnabled()
    assert dialog._view.mesh is None and dialog._loaded_deviation is None
    assert "для чтения" in dialog._quality_status.text()
    assert "100 000" in dialog._status.text()
