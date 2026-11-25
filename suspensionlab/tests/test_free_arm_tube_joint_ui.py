"""Редактор односторонней подрезки: явный выбор, несовместимость, CAD и файлы."""
from copy import deepcopy

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu
from test_free_arm_housing_io import make_draft
from test_free_arm_inner_housings import make_inner

from suspensionlab.model.free_arm_housing_io import read_independent_arm, write_free_arm_housing
from suspensionlab.model.free_arm_inner_housings_io import write_free_arm_inner_housings
from suspensionlab.model.free_arm_io import write_free_arm
from suspensionlab.model.free_arm_miter import FreeArmMiterDraft
from suspensionlab.model.free_arm_miter_io import write_free_arm_miter
from suspensionlab.model.free_arm_tube_joint import FreeArmTubeJoint, FreeArmTubeJointDraft
from suspensionlab.ui.free_arm_dialog import FreeArmDialog


def editor(qtbot, monkeypatch, *, inner=True, bent=()):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    base = make_inner(bent=bent)
    dialog._set_fields(base.arm)
    dialog._set_inner_fields(base.housings if inner else None)
    dialog.show()
    dialog.apply_fields()
    return dialog, base


def select_joint(dialog, leg='front', clearance='0.5'):
    dialog._tube_joint_choice.setCurrentIndex(dialog._tube_joint_choice.findData(leg))
    dialog._fields['tube_joint_clearance'].setText(clearance)
    dialog.apply_fields()


@pytest.mark.parametrize('leg', ['front', 'rear'])
def test_apply_save_restore_and_open(qtbot, monkeypatch, tmp_path, leg):
    dialog, base = editor(qtbot, monkeypatch)
    dialog._tube_joint_choice.setCurrentIndex(dialog._tube_joint_choice.findData(leg))
    dialog.apply_fields()
    assert dialog.tube_joint is None and not dialog._save.isEnabled() and 'Введите число' in dialog._status.text()
    dialog._fields['tube_joint_clearance'].setText('1.25')
    dialog.apply_fields()
    assert dialog.tube_joint == FreeArmTubeJoint(leg, 1.25) and dialog._cad._document['version'] == '5'
    target = tmp_path / f'{leg}.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(target), ''))
    dialog._save_file()
    assert read_independent_arm(target) == FreeArmTubeJointDraft(base.arm, dialog.tube_joint, base.housings)
    dialog._fields['tube_joint_clearance'].setText('-1')
    dialog.apply_fields()
    assert dialog.tube_joint == FreeArmTubeJoint(leg, 1.25) and dialog._cad._document is None
    dialog._restore_draft()
    assert dialog._cad._document['version'] == '5' and dialog._fields['tube_joint_clearance'].text() == '1.25'
    dialog._tube_joint_choice.setCurrentIndex(0)
    dialog.apply_fields()
    assert dialog.tube_joint is None and dialog._cad._document['version'] == '3'
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(target), ''))
    dialog._open_file()
    assert dialog.tube_joint == FreeArmTubeJoint(leg, 1.25) and dialog._cad._document['version'] == '5'
    dialog.close()


@pytest.mark.parametrize('conflict', ['miter', 'ball'])
def test_incompatible_selection_never_discards_accepted_state(qtbot, monkeypatch, conflict):
    dialog, base = editor(qtbot, monkeypatch)
    select_joint(dialog)
    before = dialog.tube_joint
    if conflict == 'miter':
        dialog._miter_check.setChecked(True)
    else:
        dialog._housing_check.setChecked(True)
    dialog.apply_fields()
    assert 'несовместима' in dialog._status.text()
    assert dialog.tube_joint == before and dialog.draft == base.arm
    assert dialog._cad._document is None and not dialog._save.isEnabled()
    dialog._restore_draft()
    assert not dialog._miter_check.isChecked() and not dialog._housing_check.isChecked()
    assert dialog._cad._document['version'] == '5' and dialog.tube_joint == before
    dialog.close()


def test_open_v1_v2_v3_v4_clears_joint_without_cross_format_loss(qtbot, monkeypatch, tmp_path):
    dialog, base = editor(qtbot, monkeypatch)
    sources = [
        write_free_arm(tmp_path / 'v1.slarm', base.arm),
        write_free_arm_housing(tmp_path / 'v2.slarm', make_draft()),
        write_free_arm_inner_housings(tmp_path / 'v3.slarm', base),
        write_free_arm_miter(tmp_path / 'v4.slarm', FreeArmMiterDraft(base.arm, base.housings)),
    ]
    for version, source in enumerate(sources, 1):
        dialog._set_housing_fields(None)
        dialog._set_miter_field(False)
        select_joint(dialog)
        assert dialog.tube_joint is not None
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_, path=source: (str(path), ''))
        dialog._open_file()
        assert dialog.tube_joint is None and dialog._tube_joint_choice.currentData() is None
        assert dialog._cad._document['version'] == str(version)
    dialog.close()


def test_save_dialog_stale_and_project_independent(qtbot, monkeypatch, tmp_path):
    from suspensionlab.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    project = deepcopy(window.controller.project.to_dict())
    window.action_free_arm.trigger()
    dialog = window._free_arm_dialog
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    base = make_inner()
    dialog._set_fields(base.arm)
    dialog._set_inner_fields(base.housings)
    dialog.apply_fields()
    select_joint(dialog)
    target = tmp_path / 'stale.slarm'
    def edit(*_):
        dialog._fields['tube_joint_clearance'].setText('2')
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', edit)
    dialog._save_file()
    assert not target.exists() and dialog.tube_joint == FreeArmTubeJoint('front', .5)
    dialog._restore_draft()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(target), ''))
    dialog._save_file()
    assert read_independent_arm(target).joint == dialog.tube_joint
    assert window.controller.project.to_dict() == project
    dialog.close()
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.close()


def test_actual_cad_works_and_failure_clears_prior_mesh(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, _ = editor(qtbot, monkeypatch, inner=False, bent=('front',))
    select_joint(dialog, 'rear', '0.5')
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    assert cad._view.mesh.part_names == ('tube_front', 'tube_rear')
    assert 'подрезана' in cad._status.text()
    dialog._fields['tube_joint_clearance'].setText('30')
    assert cad._view.mesh is None
    dialog.apply_fields()
    qtbot.waitUntil(lambda: cad._worker is None and cad._retry.isEnabled() and not cad._ready, timeout=30000)
    assert cad._view.mesh is None and 'подрезки по другой трубе' in cad._status.text()
    dialog.close()


def test_context_reveals_joint_without_changing_model(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    mesh = cad._view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('tube_front'))[0])
    dialog._settings_toggle.setChecked(False)
    def select():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text() == 'Подрезка по другой трубе…')
        qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    QTimer.singleShot(50, select)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert dialog.focusWidget() is dialog._tube_joint_choice
    assert dialog._settings_toggle.isChecked() and dialog.tube_joint is None and cad._view.mesh is mesh
    dialog.close()


def test_conflicting_context_action_disabled(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    select_joint(dialog)
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    index = int(np.flatnonzero(cad._view.mesh.triangle_parts == 0)[0])
    checked = []
    def inspect():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if 'Стык на ус недоступен: выбран рез трубы' in a.text())
        checked.append(not action.isEnabled())
        menu.close()
    QTimer.singleShot(50, inspect)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert checked == [True] and dialog.tube_joint == FreeArmTubeJoint('front', .5)
    dialog.close()
