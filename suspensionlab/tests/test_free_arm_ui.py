"""Независимый вход, изоляция проекта и актуальность предварительного CAD."""
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from suspensionlab.model.free_arm import FreeArmDraft
from suspensionlab.model.free_arm_io import read_free_arm
from suspensionlab.ui.free_arm_dialog import FreeArmDialog
from suspensionlab.ui.main_window import MainWindow


def fill(dialog):
    points = {'front': (0, 0, 0), 'rear': (0, 200, 0), 'outer': (300, 100, 10)}
    for name, point in points.items():
        for axis, number in zip('XYZ', point, strict=True):
            dialog._fields[f'{name}_{axis}'].setText(str(number))


def test_fields_apply_invalid_edit_restore_and_roundtrip(qtbot, tmp_path, monkeypatch):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.draft is None and not dialog._save.isEnabled()
    dialog.apply_fields()
    assert dialog.draft is None and 'не применены' in dialog._status.text()
    fill(dialog)
    dialog.apply_fields()
    assert isinstance(dialog.draft, FreeArmDraft)
    before = dialog.draft
    assert dialog._scene.frame is not None and dialog._projections[0].preview is not None
    assert dialog._save.isEnabled()
    dialog._fields['outer_X'].setText('0')
    assert dialog._scene.frame is None and dialog._cad._document is None and not dialog._save.isEnabled()
    dialog._fields['outer_Y'].setText('0')
    dialog._fields['outer_Z'].setText('0')
    dialog.apply_fields()
    assert dialog.draft is before and dialog._scene.frame is None
    dialog._restore_draft()
    assert dialog.draft == before and dialog._scene.frame is not None
    path = tmp_path / 'independent.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_args: (str(path), ''))
    dialog._save_file()
    assert read_free_arm(path) == before
    assert dialog.confirm_close()
    dialog._fields['front_X'].setText('20')
    dialog.apply_fields()
    assert dialog.draft != before
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_args: (str(path), ''))
    dialog._open_file()
    assert dialog.draft == before and dialog.confirm_close()
    dialog.close()


def test_optional_bend_fields_apply_and_save(qtbot, tmp_path, monkeypatch):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    fill(dialog)
    assert not dialog._fields['front_bend_X'].isEnabled()
    dialog._bend_checks['front'].setChecked(True)
    assert dialog._fields['front_bend_X'].isEnabled()
    for axis, number in zip('XYZ', (150, 20, 50), strict=True):
        dialog._fields[f'front_bend_{axis}'].setText(str(number))
    dialog._fields['front_bend_radius'].setText('20')
    dialog.apply_fields()
    assert dialog.draft is not None and dialog.draft.front_bend is not None
    path = tmp_path / 'bend.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_args: (str(path), ''))
    dialog._save_file()
    assert read_free_arm(path) == dialog.draft
    dialog._bend_checks['front'].setChecked(False)
    assert not dialog._fields['front_bend_X'].isEnabled()
    dialog.apply_fields()
    assert dialog.draft.front_bend is None
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()


def test_cancel_open_and_overwrite_do_not_replace_draft(qtbot, tmp_path, monkeypatch):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    fill(dialog)
    dialog.apply_fields()
    initial = dialog.draft
    path = tmp_path / 'exists.slarm'
    path.write_text('untouched', encoding='utf-8')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_args: (str(path), ''))
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *_args: messages.append(_args))
    dialog._save_file()
    assert messages and path.read_text() == 'untouched' and dialog.draft == initial
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.No)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_args: pytest.fail('must not open'))
    dialog._open_file()
    assert dialog.draft == initial
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()


def test_independent_menu_keeps_project_and_snapshot_entry(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    original = deepcopy(window.controller.project.to_dict())
    window.action_free_arm.trigger()
    dialog = window._free_arm_dialog
    assert dialog is not None and window.action_fixed_arm_skeleton.isEnabled()
    fill(dialog)
    dialog.apply_fields()
    assert window.controller.project.to_dict() == original
    window.controller.project.meta.name = 'изменённый проект'
    assert dialog.draft is not None and dialog._scene.frame is not None
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()
    assert window._free_arm_dialog is None
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.close()


def test_close_while_worker_is_running_and_superseded_result(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    fill(dialog)
    dialog.apply_fields()
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._worker is not None, timeout=10000)
    first_token = dialog._cad.generation
    dialog._fields['front_X'].setText('25')
    dialog.apply_fields()
    assert dialog._cad.generation > first_token and dialog._cad._view.mesh is None
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    assert dialog._cad._document['anchors_mm']['front'][0] == 25
    assert dialog._cad._view.mesh is not None
    dialog._fields['front_X'].setText('50')
    dialog.apply_fields()
    qtbot.waitUntil(lambda: dialog._cad._worker is not None, timeout=10000)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()
    assert dialog._cad._closed and (dialog._cad._worker is None or not dialog._cad._worker.isRunning())


def test_real_cad_worker_and_stale_result_are_not_shown(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    fill(dialog)
    dialog.apply_fields()
    dialog._cad._quality.setCurrentIndex(1)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    assert dialog._cad._view.mesh is not None
    assert dialog._cad._view.mesh.part_names == ('tube_front', 'tube_rear')
    assert dialog._cad._parts_tree.topLevelItem(0).childCount() == 2
    previous_token = dialog._cad.generation
    dialog._fields['front_X'].setText('4')
    assert dialog._cad._view.mesh is None and dialog._cad._document is None
    assert dialog._cad.generation > previous_token
    dialog.apply_fields()
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    assert dialog.draft.front_mm[0] == 4
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()
    assert dialog._cad._closed
