"""Форма, сброс, сохранение и открытие независимых внутренних корпусов."""
from PySide6.QtWidgets import QFileDialog
from test_free_arm_inner_housings import make_inner

from suspensionlab.model.free_arm_housing_io import read_independent_arm
from suspensionlab.ui.free_arm_dialog import FreeArmDialog


def test_apply_restore_save_open_and_disable(qtbot, monkeypatch, tmp_path):
    draft = make_inner(ball=True)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(draft.arm)
    dialog._set_housing_fields(draft.ball_housing)
    dialog._set_inner_fields(draft.housings)
    dialog.show()
    dialog.apply_fields()
    assert dialog.inner_housings == draft.housings and dialog._cad._document['version'] == '3'
    assert dialog._cad._document['notches'] == {'front': 1, 'rear': 0}
    path = tmp_path / 'inner.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_independent_arm(path) == draft
    dialog._fields['front_inner_outer'].setText('1')
    assert dialog._cad._document is None and not dialog._save.isEnabled()
    dialog.apply_fields()
    assert dialog.inner_housings == draft.housings and dialog._cad._document is None
    dialog._restore_draft()
    assert dialog._cad._document['version'] == '3'
    dialog._inner_check.setChecked(False)
    dialog.apply_fields()
    assert dialog.inner_housings is None and dialog._cad._document['version'] == '2'
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert dialog.inner_housings == draft.housings and dialog.housing == draft.ball_housing
    assert dialog._cad._document['version'] == '3'
    dialog.close()


def test_new_input_during_save_cannot_be_written(qtbot, monkeypatch, tmp_path):
    draft = make_inner()
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(draft.arm)
    dialog._set_inner_fields(draft.housings)
    dialog.show()
    dialog.apply_fields()
    path = tmp_path / 'race.slarm'
    def edit(*_):
        dialog._fields['front_inner_clearance'].setText('2')
        return str(path), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', edit)
    dialog._save_file()
    assert not path.exists() and dialog._cad._document is None
    assert dialog.inner_housings == draft.housings
    dialog.close()


def test_independent_housings_do_not_modify_project(qtbot, monkeypatch, tmp_path):
    from copy import deepcopy

    from suspensionlab.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    before = deepcopy(window.controller.project.to_dict())
    window.action_free_arm.trigger()
    dialog = window._free_arm_dialog
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    draft = make_inner(ball=True)
    dialog._set_fields(draft.arm)
    dialog._set_housing_fields(draft.ball_housing)
    dialog._set_inner_fields(draft.housings)
    dialog.apply_fields()
    target = tmp_path / 'independent.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(target), ''))
    dialog._save_file()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(target), ''))
    dialog._open_file()
    assert read_independent_arm(target) == draft
    assert window.controller.project.to_dict() == before
    dialog.close()
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.close()


def test_real_cad_updates_parts_and_clears_stale_mesh_on_cut_failure(qtbot, monkeypatch):
    import pytest

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    draft = make_inner(ball=True)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(draft.arm)
    dialog._set_housing_fields(draft.ball_housing)
    dialog._set_inner_fields(draft.housings)
    dialog.show()
    dialog.apply_fields()
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=25000)
    assert dialog._cad._view.mesh.part_names == ('tube_front', 'tube_rear', 'housing_front', 'housing_rear',
                                                 'ball_housing')
    dialog._fields['front_inner_outer'].setText('1000')
    dialog._fields['front_inner_length'].setText('2000')
    assert dialog._cad._view.mesh is None
    dialog.apply_fields()
    qtbot.waitUntil(lambda: dialog._cad._worker is None and dialog._cad._retry.isEnabled(), timeout=25000)
    assert dialog._cad._view.mesh is None and not dialog._cad._ready
    assert 'подрез' in dialog._cad._status.text().lower()
    dialog.close()
