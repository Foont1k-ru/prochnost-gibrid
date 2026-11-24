"""Общий стык: сохранение, отмена и проверка реального CAD."""
import json

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from test_fixed_arm_tube_joint_ui import make_editor


def test_miter_undo_and_reopen(qtbot, monkeypatch, tmp_path):
    _, dialog = make_editor(qtbot, monkeypatch)
    dialog._joint_clearance.setText('7')
    dialog._tube_joint.setCurrentIndex(dialog._tube_joint.findData('miter'))
    assert dialog._tube_joint_values() == {'target': 'miter', 'radial_clearance_mm': 0.}
    assert not dialog._joint_clearance.isEnabled()
    assert dialog._cad_candidate['version'] == '4'
    assert dialog._trim_undo.isEnabled()
    dialog._undo_trim()
    assert dialog._tube_joint.currentData() is None
    dialog._redo_trim()
    assert dialog._tube_joint.currentData() == 'miter'
    path = tmp_path / 'miter.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    assert json.loads(path.read_text(encoding='utf-8'))['version'] == '6'
    dialog._tube_joint.setCurrentIndex(0)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert dialog._tube_joint_values() == {'target': 'miter', 'radial_clearance_mm': 0.}
    assert dialog.confirm_close()
    dialog.close()


def test_miter_real_cad_and_geometry_change_clears_old_mesh(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    dialog._tube_joint.setCurrentIndex(dialog._tube_joint.findData('miter'))
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    assert cad._view.mesh.part_names == ('tube_front', 'tube_rear')
    assert 'обе трубы' in cad._status.text().lower()
    controller.project.front.hardpoints['lbj'].x += 1
    dialog._refresh()
    assert cad._view.mesh is None and dialog.snapshot is None
    assert dialog.shutdown()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.close()


def test_miter_worker_error_is_not_reported_as_a_crash(qtbot, monkeypatch):
    _, dialog = make_editor(qtbot, monkeypatch)
    dialog._tube_joint.setCurrentIndex(dialog._tube_joint.findData('miter'))
    cad = dialog._cad
    cad._enable.setChecked(True)
    cad._timer.stop()
    cad._failed(cad.generation, 'tube_joint_miter_failed')
    assert 'Общий стык на ус не построен' in cad._status.text()
    assert cad._view.mesh is None
    assert dialog.shutdown()
    dialog.close()
