"""Явное подтверждение корпусов, сохранение и защита от устаревания."""
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
from test_fixed_arm_housings import housings

from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_housings_dialog import FixedArmHousingsDialog
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def test_fields_are_blank_and_must_be_confirmed(qtbot):
    dialog = FixedArmHousingsDialog()
    qtbot.addWidget(dialog)
    assert all(not field.text() for fields in dialog.fields.values() for field in fields.values())
    assert not any(check.isChecked() for check in dialog.confirm_center.values())
    dialog.accept()
    assert dialog.result_values is None
    for leg, spec in housings().items():
        for key in ('outer_diameter_mm', 'bore_diameter_mm', 'length_mm'):
            dialog.fields[leg][key].setText(str(spec[key]))
        for key, value in zip(('axis_x', 'axis_y', 'axis_z'), spec['axis'], strict=True):
            dialog.fields[leg][key].setText(str(value))
    dialog.accept()
    assert dialog.result_values is None
    for check in dialog.confirm_center.values():
        check.setChecked(True)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.result_values == housings()


def test_editor_save_open_and_reset(qtbot, monkeypatch, tmp_path):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog._capture_snapshot()
    def accept(editor):
        editor.result_values = housings()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(FixedArmHousingsDialog, 'exec', accept)
    dialog._edit_housings()
    assert dialog._housings == housings()
    candidate = dialog._cad_candidate
    assert candidate is not None and dialog._cad_is_current(candidate)
    path = tmp_path / 'housing.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    assert dialog.confirm_close()
    dialog._remove_housings()
    assert dialog._housings is None and not dialog._cad_is_current(candidate)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert dialog._housings == housings() and dialog.confirm_close()
    dialog._capture_snapshot()
    assert dialog._housings is None
    dialog._edit_housings()
    controller.project.front.hardpoints['lbj'].x += 0.000001
    dialog._refresh()
    assert dialog.snapshot is None and dialog._housings is None and not dialog._housing_edit.isEnabled()
    dialog.close()


def test_real_housing_cad_updates_after_edit(qtbot, monkeypatch):
    import pytest

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.show()
    dialog._capture_snapshot()
    dialog._tabs.setCurrentIndex(4)
    dialog._cad._quality.setCurrentIndex(1)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=20000)
    anchors = dialog.preview.anchors
    def accept(editor):
        editor.result_values = housings()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(FixedArmHousingsDialog, 'exec', accept)
    dialog._edit_housings()
    assert dialog._cad._view.mesh is None
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=20000)
    assert dialog._cad._view.mesh.part_names == ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    assert dialog.preview.anchors == anchors
    assert dialog._cad._parts_tree.topLevelItem(0).childCount() == 4
    dialog._remove_housings()
    assert dialog._cad._view.mesh is None
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=20000)
    assert dialog._cad._view.mesh.part_names == ('tube_front', 'tube_rear')
    assert dialog.shutdown()
    dialog.close()


def test_project_change_during_modal_input_rejected(qtbot, monkeypatch):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog._capture_snapshot()
    def modify(editor):
        editor.result_values = housings()
        controller.project.front.hardpoints['lbj'].x += 1
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(FixedArmHousingsDialog, 'exec', modify)
    dialog._edit_housings()
    assert dialog._housings is None and dialog.snapshot is None and dialog.preview is None
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.close()
