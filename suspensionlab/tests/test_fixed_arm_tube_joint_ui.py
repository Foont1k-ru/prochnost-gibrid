"""Выбор направления, явный зазор, пересчёт и восстановление рецепта."""
import json

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
from test_fixed_arm_housings import housings

from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_housings_dialog import FixedArmHousingsDialog
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def make_editor(qtbot, monkeypatch):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.show()
    dialog._capture_snapshot()
    dialog._tabs.setCurrentIndex(4)
    dialog._cad_tools.setCurrentIndex(1)
    return controller, dialog


def test_explicit_choice_save_restore_and_stale(qtbot, monkeypatch, tmp_path):
    controller, dialog = make_editor(qtbot, monkeypatch)
    anchors = dialog.preview.anchors
    assert dialog._tube_joint.currentData() is None and not dialog._joint_clearance.text()
    assert dialog._tube_joint.isEnabled() and not dialog._joint_clearance.isEnabled()
    old = dialog._cad_candidate
    dialog._tube_joint.setCurrentIndex(dialog._tube_joint.findData('rear'))
    assert not dialog._save.isEnabled() and dialog._cad_candidate is None
    assert not dialog._cad_is_current(old) and 'зазор' in dialog._notch_status.text()
    field = dialog._joint_clearance
    dialog.activateWindow()
    field.setFocus()
    qtbot.waitUntil(field.hasFocus)
    qtbot.keyClicks(field, '0.5')
    assert field.text() == '0.5' and field.hasFocus()
    candidate = dialog._cad_candidate
    assert candidate['tube_joint'] == {'target': 'rear', 'radial_clearance_mm': 0.5}
    assert candidate['housings'] is None and dialog._cad_is_current(candidate)
    field.setText('nan')
    assert dialog._cad_candidate is None and not dialog._save.isEnabled()
    field.setText('0.5')
    path = tmp_path / 'joint.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['version'] == '4' and data['geometry']['tube_joint']['target'] == 'rear'
    dialog._tube_joint.setCurrentIndex(dialog._tube_joint.findData('front'))
    assert dialog._state() != dialog._saved_state
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert dialog._tube_joint_values() == {'target': 'rear', 'radial_clearance_mm': 0.5}
    assert dialog.preview.anchors == anchors and dialog.confirm_close()
    controller.project.front.hardpoints['lbj'].x += 1
    dialog._refresh()
    assert dialog.snapshot is None and not dialog._tube_joint.isEnabled()
    assert dialog._tube_joint.currentData() is None and dialog._cad_candidate is None
    dialog.close()


def test_housing_changes_reset_housing_cuts_but_keep_independent_tube_cut(qtbot, monkeypatch):
    _, dialog = make_editor(qtbot, monkeypatch)
    dialog._tube_joint.setCurrentIndex(dialog._tube_joint.findData('rear'))
    dialog._joint_clearance.setText('0.5')
    def accept(modal):
        modal.result_values = housings()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(FixedArmHousingsDialog, 'exec', accept)
    dialog._edit_housings()
    assert dialog._tube_joint_values() == {'target': 'rear', 'radial_clearance_mm': 0.5}
    dialog._notch_checks['front'].setChecked(True)
    dialog._notch_clearances['front'].setText('2')
    dialog._remove_housings()
    assert dialog._notch_values() is None
    assert dialog._tube_joint_values() == {'target': 'rear', 'radial_clearance_mm': 0.5}
    assert dialog._cad_candidate['housings'] is None
    assert dialog.shutdown()
    dialog.close()


def test_actual_cad_cut_and_revert(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    old_mesh = cad._view.mesh
    dialog._tube_joint.setCurrentIndex(dialog._tube_joint.findData('front'))
    assert cad._view.mesh is None
    dialog._joint_clearance.setText('0')
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    assert cad._view.mesh is not old_mesh
    assert cad._view.mesh.part_names == ('tube_front', 'tube_rear')
    assert 'подрезана' in cad._status.text()
    dialog._tube_joint.setCurrentIndex(0)
    assert cad._view.mesh is None
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    assert cad._document['version'] in ('0.2', '0.3')
    assert dialog.shutdown()
    dialog.close()


def test_joint_error_labels_both_tubes(qtbot, monkeypatch):
    _, dialog = make_editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._enable.setChecked(True)
    cad._timer.stop()
    cad._failed(cad.generation, 'tube_joint_front_no_overlap')
    assert 'Передняя ветвь' in cad._status.text() and 'другой трубой' in cad._status.text()
    assert cad._view.mesh is None and dialog._save.isEnabled()
    assert dialog.shutdown()
    dialog.close()
