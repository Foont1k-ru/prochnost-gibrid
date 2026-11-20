"""Временная подрезка: явные зазоры, отдельные ветви и запрет устаревшего CAD."""
import json

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
from test_fixed_arm_housings import housings

from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_housings_dialog import FixedArmHousingsDialog
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def editor(qtbot, monkeypatch):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.show()
    dialog._capture_snapshot()
    def accept(modal):
        modal.result_values = housings()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(FixedArmHousingsDialog, 'exec', accept)
    dialog._edit_housings()
    dialog._tabs.setCurrentIndex(4)
    return controller, dialog


def test_explicit_values_independent_and_not_saved(qtbot, monkeypatch, tmp_path):
    controller, dialog = editor(qtbot, monkeypatch)
    anchors = dialog.preview.anchors
    assert all(not c.isChecked() for c in dialog._notch_checks.values())
    assert all(not f.text() for f in dialog._notch_clearances.values())
    old = dialog._cad_candidate
    dialog._notch_checks['front'].setChecked(True)
    assert dialog.preview is not None and dialog._save.isEnabled()
    assert dialog._cad_candidate is None and not dialog._cad_is_current(old)
    assert 'зазор' in dialog._notch_status.text()
    front = dialog._notch_clearances['front']
    dialog.activateWindow()
    front.setFocus()
    qtbot.waitUntil(front.hasFocus)
    qtbot.keyClicks(front, '1.25')
    assert front.text() == '1.25' and front.hasFocus()
    assert dialog._cad_candidate['notches'] == {'front': 1.25}
    assert dialog._cad_is_current(dialog._cad_candidate)
    dialog._notch_checks['rear'].setChecked(True)
    dialog._notch_clearances['rear'].setText('0')
    assert dialog._cad_candidate['notches'] == {'front': 1.25, 'rear': 0.0}
    dialog._notch_clearances['rear'].setText('-1')
    assert dialog._cad_candidate is None and dialog.preview.anchors == anchors
    dialog._notch_clearances['rear'].setText('0')
    path = tmp_path / 'saved.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    data = json.loads(path.read_text(encoding='utf-8'))
    assert 'notches' not in data['geometry'] and data['geometry']['housings'] == housings()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert all(not c.isChecked() for c in dialog._notch_checks.values())
    assert all(not f.text() for f in dialog._notch_clearances.values())
    assert dialog._housings == housings() and dialog.preview.anchors == anchors
    dialog._notch_checks['front'].setChecked(True)
    dialog._notch_clearances['front'].setText('0')
    controller.project.front.hardpoints['lbj'].x += 1
    dialog._refresh()
    assert dialog.snapshot is None and not dialog._notch_checks['front'].isChecked()
    assert dialog._cad_candidate is None and not dialog._notch_checks['front'].isEnabled()
    dialog.close()


def test_failure_message_keeps_skeleton_and_hides_cad(qtbot, monkeypatch):
    _, dialog = editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._enable.setChecked(True)
    cad._timer.stop()
    cad._failed(cad.generation, 'notch_rear_empty_or_split')
    assert cad._view.mesh is None and not cad._ready
    assert 'Задняя ветвь' in cad._status.text() and 'на части' in cad._status.text()
    assert dialog.preview is not None and dialog._save.isEnabled()
    assert dialog.shutdown()
    dialog.close()


def test_real_cad_rebuilds_and_toggle_reverts(qtbot, monkeypatch):
    import pytest

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    original = cad._view.mesh
    dialog._notch_checks['front'].setChecked(True)
    assert cad._view.mesh is None
    dialog._notch_clearances['front'].setText('0')
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    assert cad._view.mesh is not original and cad._view.mesh.part_names == original.part_names
    assert 'подрезаны' in cad._status.text() and dialog._cad_candidate['notches'] == {'front': 0}
    dialog._notch_checks['front'].setChecked(False)
    assert cad._view.mesh is None
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    assert 'неподрезанные' in cad._status.text()
    assert dialog.shutdown()
    dialog.close()
