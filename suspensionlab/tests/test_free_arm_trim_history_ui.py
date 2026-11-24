"""История принятых подрезок в независимом редакторе."""
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from test_free_arm_inner_housings import make_inner
from test_free_arm_tube_joint_ui import editor, select_joint

from suspensionlab.model.free_arm_housing_io import read_independent_arm
from suspensionlab.model.free_arm_io import write_free_arm
from suspensionlab.model.free_arm_tube_joint import FreeArmTubeJoint


def click(qtbot, button):
    assert button.isEnabled()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def test_history_of_accepted_notches_joint_and_miter(qtbot, monkeypatch, tmp_path):
    dialog, base = editor(qtbot, monkeypatch)
    initial = dialog._form()
    assert not dialog._trim_undo.isEnabled() and not dialog._trim_redo.isEnabled()
    dialog._inner_notch['front'].setChecked(False)
    dialog.apply_fields()
    no_front = dialog._form()
    assert dialog.inner_housings.front_clearance_mm is None
    select_joint(dialog, 'rear', '0,50')
    joint_form = dialog._form()
    assert dialog._cad._document['version'] == '5'
    click(qtbot, dialog._trim_undo)
    assert dialog._form() == no_front and dialog.tube_joint is None and dialog._cad._document['version'] == '3'
    click(qtbot, dialog._trim_undo)
    assert dialog._form() == initial and dialog.inner_housings == base.housings
    assert not dialog._trim_undo.isEnabled()
    click(qtbot, dialog._trim_redo)
    click(qtbot, dialog._trim_redo)
    assert dialog._form() == joint_form and dialog.tube_joint == FreeArmTubeJoint('rear', .5)
    assert not dialog._trim_redo.isEnabled()
    path = tmp_path / 'new.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    saved = read_independent_arm(path)
    click(qtbot, dialog._trim_undo)
    assert dialog._saved_form != dialog._form()
    click(qtbot, dialog._trim_redo)
    assert dialog._saved_form == dialog._form() and read_independent_arm(path) == saved
    dialog._tube_joint_choice.setCurrentIndex(0)
    dialog._miter_check.setChecked(True)
    dialog.apply_fields()
    assert dialog.miter and dialog._cad._document['version'] == '4'
    click(qtbot, dialog._trim_undo)
    assert not dialog.miter and dialog.tube_joint == FreeArmTubeJoint('rear', .5)
    click(qtbot, dialog._trim_redo)
    assert dialog.miter and dialog.tube_joint is None
    dialog.close()


def test_unaccepted_and_invalid_input_never_discarded_by_history(qtbot, monkeypatch):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    select_joint(dialog)
    accepted = dialog._trim_state()
    dialog._fields['tube_joint_clearance'].setText('-1')
    assert not dialog._trim_undo.isEnabled()
    dialog._undo_trim()  # even a programmatic invocation is rejected
    assert dialog._fields['tube_joint_clearance'].text() == '-1' and dialog.tube_joint == accepted.joint
    dialog.apply_fields()
    assert not dialog._trim_undo.isEnabled() and dialog._cad._document is None
    dialog._undo_trim()
    assert dialog._fields['tube_joint_clearance'].text() == '-1' and dialog.tube_joint == accepted.joint
    dialog._restore_draft()
    assert dialog._trim_undo.isEnabled() and dialog._trim_state() == accepted
    click(qtbot, dialog._trim_undo)
    assert dialog.tube_joint is None
    dialog.close()


def test_branching_noop_and_geometry_change_reset_history(qtbot, monkeypatch):
    dialog, base = editor(qtbot, monkeypatch, inner=False)
    select_joint(dialog, 'front', '1')
    select_joint(dialog, 'rear', '2')
    click(qtbot, dialog._trim_undo)
    assert dialog.tube_joint == FreeArmTubeJoint('front', 1)
    dialog.apply_fields()  # no-op must not discard redo
    assert dialog._trim_redo.isEnabled()
    select_joint(dialog, 'front', '3')
    assert not dialog._trim_redo.isEnabled()
    click(qtbot, dialog._trim_undo)
    assert dialog.tube_joint == FreeArmTubeJoint('front', 1)
    dialog._fields['front_X'].setText('2')
    dialog.apply_fields()
    assert dialog.draft.front_mm[0] == 2 and dialog.draft != base.arm
    assert not dialog._trim_undo.isEnabled() and not dialog._trim_redo.isEnabled()
    dialog.close()


def test_housing_changes_and_open_reset_history(qtbot, monkeypatch, tmp_path):
    dialog, base = editor(qtbot, monkeypatch)
    dialog._inner_notch['front'].setChecked(False)
    dialog.apply_fields()
    assert dialog._trim_undo.isEnabled()
    dialog._fields['front_inner_outer'].setText('41')
    dialog.apply_fields()
    assert dialog.inner_housings.front.outer_diameter_mm == 41 and not dialog._trim_undo.isEnabled()
    select_joint(dialog)
    assert dialog._trim_undo.isEnabled()
    path = write_free_arm(tmp_path / 'old.slarm', base.arm)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert dialog.draft == base.arm and dialog.inner_housings is None and dialog.tube_joint is None
    assert not dialog._trim_undo.isEnabled() and not dialog._trim_redo.isEnabled()
    dialog.close()


def test_projection_session_blocks_undo_even_if_invoked_directly(qtbot, monkeypatch):
    dialog, base = editor(qtbot, monkeypatch, inner=False, bent=('front',))
    select_joint(dialog)
    dialog._tabs.setCurrentWidget(dialog._projections[0])
    dialog._projection_point(dialog._projections[0], 'bend_front')
    assert dialog._projection_session is not None and not dialog._trim_undo.isEnabled()
    dialog._undo_trim()
    assert dialog.tube_joint == FreeArmTubeJoint('front', .5) and dialog.draft == base.arm
    dialog._close_projection_session()
    assert dialog._trim_undo.isEnabled()
    dialog.close()


def test_real_cad_undo_redo_and_failed_cut_never_restores_old_mesh(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, _ = editor(qtbot, monkeypatch, inner=False, bent=('front',))
    select_joint(dialog, 'rear', '.5')
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    valid = cad._view.mesh
    select_joint(dialog, 'rear', '30')
    assert cad._view.mesh is None
    qtbot.waitUntil(lambda: cad._worker is None and cad._retry.isEnabled() and not cad._ready, timeout=30000)
    assert cad._view.mesh is None
    click(qtbot, dialog._trim_undo)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    assert dialog.tube_joint == FreeArmTubeJoint('rear', .5) and cad._view.mesh is not None
    click(qtbot, dialog._trim_redo)
    assert cad._view.mesh is None
    qtbot.waitUntil(lambda: cad._worker is None and cad._retry.isEnabled() and not cad._ready, timeout=30000)
    assert cad._view.mesh is None and valid is not cad._view.mesh
    dialog.close()


def test_independent_history_never_mutates_open_project(qtbot, monkeypatch):
    from suspensionlab.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    before = deepcopy(window.controller.project.to_dict())
    window.action_free_arm.trigger()
    dialog = window._free_arm_dialog
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(make_inner().arm)
    dialog.apply_fields()
    select_joint(dialog)
    click(qtbot, dialog._trim_undo)
    click(qtbot, dialog._trim_redo)
    assert window.controller.project.to_dict() == before
    dialog.close()
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.close()


def test_restore_unchanged_accepted_text_preserves_redo_branch(qtbot, monkeypatch):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    select_joint(dialog, 'front', '0,50')
    select_joint(dialog, 'rear', '1,50')
    click(qtbot, dialog._trim_undo)
    before, count = dialog._form(), len(dialog._trim_history)
    dialog._fields['tube_joint_clearance'].setText('invalid')
    dialog._restore_draft()
    assert dialog._fields['tube_joint_clearance'].text() == '0,50'
    assert dialog._form() == before and len(dialog._trim_history) == count and dialog._trim_redo.isEnabled()
    click(qtbot, dialog._trim_redo)
    assert dialog._fields['tube_joint_clearance'].text() == '1,50'
    dialog.close()


def test_history_limits_memory_and_saves_only_current_state(qtbot, monkeypatch, tmp_path):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    for value in range(110):
        select_joint(dialog, 'front', str(value % 101))
    assert len(dialog._trim_history) == 101 and dialog._trim_history_index == 100
    click(qtbot, dialog._trim_undo)
    path = tmp_path / 'history.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_independent_arm(path).joint == dialog.tube_joint
    assert 'history' not in path.read_text(encoding='utf-8')
    dialog.close()


def test_undo_while_file_dialog_open_discards_stale_result(qtbot, monkeypatch, tmp_path):
    dialog, base = editor(qtbot, monkeypatch, inner=False)
    select_joint(dialog)
    path = tmp_path / 'must-not-write.slarm'
    def choose(*_):
        click(qtbot, dialog._trim_undo)
        return str(path), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    dialog._save_file()
    assert not path.exists() and dialog.draft == base.arm and dialog.tube_joint is None
    dialog.close()


def test_inline_session_blocks_history_until_cancel(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, base = editor(qtbot, monkeypatch, inner=False, bent=('front',))
    select_joint(dialog)
    dialog._tabs.setCurrentWidget(dialog._cad)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    dialog._open_inline_sketch('front')
    assert dialog._inline_session is not None and not dialog._trim_undo.isEnabled()
    dialog._undo_trim()
    assert dialog.tube_joint == FreeArmTubeJoint('front', .5) and dialog.draft == base.arm
    dialog._close_inline_sketch()
    assert dialog._trim_undo.isEnabled()
    dialog.close()


def test_rapid_undo_redo_discards_late_worker_result_and_close_cancels(qtbot, monkeypatch):
    import threading

    import numpy as np

    from suspensionlab.core.cad_mesh import CadMesh
    from suspensionlab.ui import weldment_3d

    jobs = []
    class Job:
        def __init__(self):
            self.started, self.release = threading.Event(), threading.Event()
            self.cancelled = False
            jobs.append(self)
        def cancel(self):
            self.cancelled = True
            if self is jobs[-1] and len(jobs) >= 3:
                self.release.set()  # allow shutdown; the first job deliberately returns late
        def run(self, document, *, deviation=2.):
            marker = len(jobs)
            self.started.set()
            assert self.release.wait(10)
            return CadMesh(np.array([[[marker, 0, 0], [marker, 1, 0], [marker, 0, 1]],
                                     [[marker, 2, 0], [marker, 3, 0], [marker, 2, 1]]]), 2,
                           part_names=('tube_front', 'tube_rear'), triangle_parts=np.array([0, 1]))
    monkeypatch.setattr(weldment_3d, 'WeldmentCadJob', Job)
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    select_joint(dialog)
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: len(jobs) == 1 and jobs[0].started.is_set(), timeout=5000)
    generation = cad.generation
    click(qtbot, dialog._trim_undo)
    click(qtbot, dialog._trim_redo)
    assert jobs[0].cancelled and cad.generation > generation and cad._view.mesh is None
    jobs[0].release.set()
    qtbot.waitUntil(lambda: len(jobs) == 2 and jobs[1].started.is_set(), timeout=5000)
    assert cad._view.mesh is None
    jobs[1].release.set()
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=5000)
    assert cad._view.mesh.triangles[0, 0, 0] == 2 and dialog.tube_joint == FreeArmTubeJoint('front', .5)
    select_joint(dialog, 'front', '2')
    qtbot.waitUntil(lambda: len(jobs) == 3 and jobs[2].started.is_set(), timeout=5000)
    dialog.close()
    assert jobs[2].cancelled and cad._closed and (cad._worker is None or not cad._worker.isRunning())


def test_history_buttons_accessible_after_reopening_parameters(qtbot, monkeypatch):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    select_joint(dialog)
    dialog._settings_toggle.setChecked(False)
    assert not dialog._trim_undo.isVisible()
    dialog._settings_toggle.setChecked(True)
    dialog._parameters_scroll.ensureWidgetVisible(dialog._trim_undo)
    qtbot.waitUntil(lambda: dialog._trim_undo.isVisible())
    rect = dialog._trim_undo.rect()
    top_left = dialog._trim_undo.mapTo(dialog._parameters_scroll.viewport(), rect.topLeft())
    bottom_right = dialog._trim_undo.mapTo(dialog._parameters_scroll.viewport(), rect.bottomRight())
    viewport = dialog._parameters_scroll.viewport().rect()
    assert viewport.contains(top_left) and viewport.contains(bottom_right)
    assert dialog._trim_undo.fontMetrics().horizontalAdvance(dialog._trim_undo.text()) + 16 <= rect.width()
    click(qtbot, dialog._trim_undo)
    assert dialog.tube_joint is None and dialog._trim_redo.isEnabled()
    dialog.close()


def test_central_housing_with_inner_notches_is_not_rolled_back(qtbot, monkeypatch):
    dialog, _ = editor(qtbot, monkeypatch)
    base = make_inner(ball=True)
    dialog._set_housing_fields(base.ball_housing)
    dialog.apply_fields()
    assert dialog.housing == base.ball_housing and dialog._cad._document['version'] == '3'
    assert not dialog._trim_undo.isEnabled()
    dialog._inner_notch['rear'].setChecked(False)
    dialog.apply_fields()
    assert dialog.inner_housings.rear_clearance_mm is None
    click(qtbot, dialog._trim_undo)
    assert dialog.housing == base.ball_housing and dialog.inner_housings == base.housings
    assert dialog._cad._document['version'] == '3'
    dialog._fields['housing_outer'].setText('125')
    dialog.apply_fields()
    assert dialog.housing.outer_diameter_mm == 125
    assert not dialog._trim_undo.isEnabled() and not dialog._trim_redo.isEnabled()
    dialog.close()
