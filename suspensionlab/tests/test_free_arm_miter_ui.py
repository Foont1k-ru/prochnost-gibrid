"""Независимый стык: UI, актуальность, файл и реальный CAD."""
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu
from test_free_arm_housing_io import make_draft
from test_free_arm_inner_housings import make_inner

from suspensionlab.model.free_arm_housing_io import read_independent_arm
from suspensionlab.model.free_arm_miter import FreeArmMiterDraft
from suspensionlab.model.free_arm_miter_io import write_free_arm_miter
from suspensionlab.ui.free_arm_dialog import FreeArmDialog


def editor(qtbot, monkeypatch, *, inner=True):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    base = make_inner(cuts=True)
    dialog._set_fields(base.arm)
    dialog._set_inner_fields(base.housings if inner else None)
    dialog.show()
    dialog.apply_fields()
    return dialog, base


def test_apply_restore_save_reopen_and_incompatible_central(qtbot, monkeypatch, tmp_path):
    dialog, base = editor(qtbot, monkeypatch)
    dialog._miter_check.setChecked(True)
    assert not dialog._save.isEnabled() and dialog._cad._document is None
    dialog.apply_fields()
    assert dialog.miter and dialog._cad._document['version'] == '4'
    assert dialog._cad._document['notches'] == {'front': 1, 'rear': 0}
    path = tmp_path / 'miter.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_independent_arm(path) == FreeArmMiterDraft(base.arm, base.housings)
    dialog._housing_check.setChecked(True)
    dialog.apply_fields()
    assert 'несовместим' in dialog._status.text() and dialog.miter
    assert dialog._cad._document is None and not dialog._save.isEnabled()
    dialog._restore_draft()
    assert not dialog._housing_check.isChecked() and dialog._miter_check.isChecked()
    assert dialog._cad._document['version'] == '4'
    dialog._miter_check.setChecked(False)
    dialog.apply_fields()
    assert not dialog.miter and dialog._cad._document['version'] == '3'
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert dialog.miter and dialog._miter_check.isChecked() and dialog.inner_housings == base.housings
    assert dialog._cad._document['version'] == '4'
    dialog.close()


def test_file_open_v1_and_v2_clears_old_miter(qtbot, monkeypatch, tmp_path):
    from suspensionlab.model.free_arm_housing_io import write_free_arm_housing
    from suspensionlab.model.free_arm_io import write_free_arm

    dialog, base = editor(qtbot, monkeypatch)
    dialog._miter_check.setChecked(True)
    dialog.apply_fields()
    v1 = write_free_arm(tmp_path / 'v1.slarm', base.arm)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(v1), ''))
    dialog._open_file()
    assert not dialog.miter and not dialog._miter_check.isChecked() and dialog._cad._document['version'] == '1'
    v2 = write_free_arm_housing(tmp_path / 'v2.slarm', make_draft())
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(v2), ''))
    dialog._open_file()
    assert not dialog.miter and not dialog._miter_check.isChecked() and dialog._cad._document['version'] == '2'
    dialog.close()


def test_save_cancelled_if_miter_changes_while_dialog_open(qtbot, monkeypatch, tmp_path):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    dialog._miter_check.setChecked(True)
    dialog.apply_fields()
    target = tmp_path / 'race.slarm'
    def change(*_):
        dialog._miter_check.setChecked(False)
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', change)
    dialog._save_file()
    assert not target.exists() and dialog.miter and dialog._cad._document is None
    dialog.close()


def test_actual_cad_build_and_failed_cut_has_no_stale_mesh(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, base = editor(qtbot, monkeypatch)
    dialog._miter_check.setChecked(True)
    dialog.apply_fields()
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    assert cad._view.mesh.part_names == ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    assert 'на ус' in cad._status.text()
    dialog._fields['rear_Y'].setText('0.1')
    assert cad._view.mesh is None
    dialog.apply_fields()
    qtbot.waitUntil(lambda: cad._worker is None and cad._retry.isEnabled() and not cad._ready, timeout=30000)
    assert cad._view.mesh is None and 'Общий стык на ус не построен' in cad._status.text()
    assert dialog.draft != base.arm and dialog.miter
    dialog.close()


def test_context_menu_focuses_miter_without_changing_document(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    mesh = cad._view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('tube_rear'))[0])
    dialog._settings_toggle.setChecked(False)
    def select():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text().startswith('Общий стык'))
        assert action.isEnabled()
        qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    QTimer.singleShot(50, select)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert dialog._settings_toggle.isChecked() and dialog.focusWidget() is dialog._miter_check
    assert not dialog.miter and not dialog._miter_check.isChecked() and cad._view.mesh is mesh
    dialog.close()


def test_opening_valid_file_with_geometrically_impossible_joint_preserves_parameters(qtbot, monkeypatch, tmp_path):
    draft = make_draft()
    invalid = replace(draft.arm, rear_mm=(0, .1, 0))
    path = write_free_arm_miter(tmp_path / 'bad-cad.slarm', FreeArmMiterDraft(invalid))
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert dialog.draft == invalid and dialog.miter and dialog._cad._document['version'] == '4'
    dialog.close()


def test_v4_changes_never_modify_open_suspension_project(qtbot, monkeypatch, tmp_path):
    from copy import deepcopy

    from suspensionlab.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    original = deepcopy(window.controller.project.to_dict())
    window.action_free_arm.trigger()
    dialog = window._free_arm_dialog
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    base = make_inner()
    dialog._set_fields(base.arm)
    dialog._set_inner_fields(base.housings)
    dialog._miter_check.setChecked(True)
    dialog.apply_fields()
    path = tmp_path / 'miter.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert read_independent_arm(path) == FreeArmMiterDraft(base.arm, base.housings)
    assert window.controller.project.to_dict() == original
    dialog.close()
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.close()


def test_central_housing_explains_why_miter_is_disabled_in_context(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    dialog._set_housing_fields(make_draft().housing)
    dialog.apply_fields()
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    mesh = cad._view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('tube_front'))[0])
    def inspect():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text().startswith('Стык на ус недоступен'))
        assert not action.isEnabled() and 'центральным корпусом' in action.text()
        assert menu.width() <= menu.screen().availableGeometry().width()
        menu.close()
    QTimer.singleShot(50, inspect)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert dialog.housing == make_draft().housing and not dialog.miter and cad._view.mesh is mesh
    dialog.close()
