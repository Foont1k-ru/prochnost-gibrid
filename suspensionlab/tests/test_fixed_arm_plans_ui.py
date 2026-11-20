"""План остаётся предложением, применяется одним действием и перепроверяется."""
import threading
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from test_fixed_arm_housings import housings
from test_fixed_arm_overlap_all_ui import make_dialog

from suspensionlab.core.cad_fixed_arm_overlap_job import PlanResult, ProximityResult
from suspensionlab.ui import fixed_arm_overlap as overlap_ui


def test_real_two_cuts_need_confirmation_undo_as_one_and_save(qtbot, monkeypatch, tmp_path):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    h = housings()
    h['front']['axis'] = [1, 0, 0]
    h['front']['length_mm'] = 40
    dialog._housings = h
    dialog._radius.setValue(10)
    dialog._refresh()
    view = dialog._overlap
    req = {'tube_front|tube_rear': 0, 'tube_front|housing_front': .5}
    view.set_requirements(req, housings=True)
    original_project = deepcopy(controller.project.to_dict())
    view._start_plan()
    qtbot.waitUntil(lambda: view._worker is None, timeout=180000)
    assert view._plan_result is not None, (view._status.text(), view._auto_summary.text())
    assert len(view._plan_result.actions) == 2 and view._comparison.rowCount() == 6
    assert view._comparison_button.isEnabled() and view._apply_button.isEnabled()
    view._open_comparison()
    assert view._comparison_dialog.isVisible()
    view._table.selectRow(1)
    assert view._plan_result is not None and view._apply_button.isEnabled()
    assert dialog._tube_joint_values() is None and dialog._notch_values() is None
    unaccepted = tmp_path / 'unaccepted.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(unaccepted), ''))
    dialog._save_file()
    import json
    saved = json.loads(unaccepted.read_text(encoding='utf-8'))
    assert saved['geometry']['tube_joint'] is None and saved['geometry']['notches'] is None
    assert view._plan_result is not None
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.No)
    view._confirm_suggestion()
    assert view._plan_result is not None and dialog._tube_joint_values() is None
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    view._confirm_suggestion()
    qtbot.waitUntil(lambda: view._worker is None, timeout=180000)
    assert dialog._tube_joint_values() is not None and dialog._notch_values() == {'front': 1.0}
    assert view.requirements() == req and view._plan_result is None and view._comparison_dialog.isHidden()
    assert view._proximity is not None and view._table.rowCount() == 6  # automatic fresh scan
    assert controller.project.to_dict() == original_project
    dialog._undo_trim()
    assert dialog._tube_joint_values() is None and dialog._notch_values() is None
    assert not dialog._trim_undo.isEnabled() and dialog._trim_redo.isEnabled()
    dialog._redo_trim()
    assert dialog._tube_joint_values() is not None and dialog._notch_values() == {'front': 1.0}
    path = tmp_path / 'two-cuts.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), ''))
    dialog._save_file()
    assert path.exists()
    dialog._undo_trim()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    dialog._open_file()
    assert dialog._tube_joint_values() is not None and dialog._notch_values() == {'front': 1.0}
    assert view.requirements() == req and view._table.isHidden() and view._plan_result is None
    assert dialog.shutdown()
    dialog.close()


def test_plan_cancel_or_geometry_edit_drops_late_result(qtbot, monkeypatch):
    started = threading.Event()
    class SlowJob:
        def __init__(self):
            self.stopped = threading.Event()
        def cancel(self):
            self.stopped.set()
        def run_plan(self, doc, req):
            started.set()
            self.stopped.wait(5)
            return PlanResult('insufficient', ProximityResult(()))
    monkeypatch.setattr(overlap_ui, 'FixedArmOverlapJob', SlowJob)
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    view.set_requirements({'tube_front|tube_rear': 0, 'tube_front|housing_front': .5}, housings=True)
    view._start_plan()
    assert started.wait(2)
    view._cancel_check()
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert view._plan_result is None and view._table.isHidden() and not view._apply_button.isEnabled()
    view._start_plan()
    dialog._radius.setValue(dialog._radius.value() + 1)
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert view._plan_result is None and view._table.isHidden()
    assert dialog.shutdown()
    dialog.close()


def test_plan_requires_explicit_requirements_and_no_drafts(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    view._start_plan()
    assert view._worker is None and 'как минимум два' in view._auto_summary.text()
    view.set_requirements({'tube_front|tube_rear': 0, 'tube_front|housing_front': .5}, housings=True)
    from suspensionlab.core.cad_fixed_arm_overlap_job import PairProximity, ProximityResult
    view._completed(view.generation, ProximityResult((PairProximity('tube_front', 'tube_rear', 1, 1e-6, 0),)))
    view._minimum.setText('1')
    view._start_plan()
    assert view._worker is None and 'черновики' in view._auto_summary.text()
    assert dialog.shutdown()
    dialog.close()


def test_stale_plan_or_changed_requirements_cannot_be_applied(qtbot, monkeypatch):
    from test_fixed_arm_plans import measurements

    from suspensionlab.core import fixed_arm_plans as plans
    from suspensionlab.core.cad_fixed_arm_overlap_job import _parse_plan

    controller, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    req = {'tube_front|tube_rear': 0, 'tube_front|housing_front': .5}
    view.set_requirements(req, housings=True)
    doc = dialog._cad_candidate
    monkeypatch.setattr(plans, 'measure_proximity', measurements)
    request = {'document': doc, 'requirements': req}
    plan = _parse_plan({'status': 'ok', **plans.suggest_plan(request)}, request)
    view._completed(view.generation, plan)
    assert view._plan_result is plan and view._apply_button.isEnabled()
    def change_during_confirm(*args):
        view.set_requirements({'tube_front|tube_rear': 0, 'tube_front|housing_front': 2}, housings=True)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', change_during_confirm)
    view._confirm_suggestion()
    assert dialog._tube_joint_values() is None and dialog._notch_values() is None
    assert view._plan_result is None and not view._apply_button.isEnabled()
    view.set_requirements(req, housings=True)
    view._completed(view.generation, plan)
    def change_project(*args):
        controller.project.front.hardpoints['lbj'].x += 1
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', change_project)
    view._confirm_suggestion()
    assert dialog._tube_joint_values() is None and dialog._notch_values() is None
    assert view._plan_result is None and view._table.isHidden()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    assert dialog.shutdown()
    dialog.close()


def test_incomplete_plan_is_rejected_without_updating_controls(qtbot, monkeypatch):
    from test_fixed_arm_plans import measurements

    from suspensionlab.core import fixed_arm_plans as plans
    from suspensionlab.core.cad_fixed_arm_overlap_job import PlanAction, _parse_plan

    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    req = {'tube_front|tube_rear': 0, 'tube_front|housing_front': .5}
    view.set_requirements(req, housings=True)
    doc = dialog._cad_candidate
    monkeypatch.setattr(plans, 'measure_proximity', measurements)
    request = {'document': doc, 'requirements': req}
    valid = _parse_plan({'status': 'ok', **plans.suggest_plan(request)}, request)
    forged = PlanResult('candidate', valid.baseline,
                        (valid.actions[0], PlanAction(valid.actions[0].pair, 'joint', 'rear', 0)), valid.after)
    dialog._apply_cut_suggestion(doc, forged)
    assert dialog._tube_joint_values() is None and dialog._notch_values() is None
    assert not dialog._trim_undo.isEnabled()
    assert dialog.shutdown()
    dialog.close()


def test_plan_mismatch_rolls_back_both_cuts_without_history(qtbot, monkeypatch):
    from test_fixed_arm_plans import measurements

    from suspensionlab.core import fixed_arm_plans as plans
    from suspensionlab.core.cad_fixed_arm_overlap_job import _parse_plan

    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    req = {'tube_front|tube_rear': 0, 'tube_front|housing_front': .5}
    view.set_requirements(req, housings=True)
    doc = deepcopy(dialog._cad_candidate)
    monkeypatch.setattr(plans, 'measure_proximity', measurements)
    request = {'document': doc, 'requirements': req}
    plan = _parse_plan({'status': 'ok', **plans.suggest_plan(request)}, request)
    refresh = dialog._refresh
    calls = []
    def mismatch_once():
        refresh()
        calls.append(1)
        if len(calls) == 1:
            dialog._cad_candidate = None
    monkeypatch.setattr(dialog, '_refresh', mismatch_once)
    dialog._apply_cut_suggestion(doc, plan)
    assert len(calls) == 2 and dialog._cad_candidate == doc
    assert dialog._tube_joint_values() is None and dialog._notch_values() is None
    assert not dialog._trim_undo.isEnabled() and 'отменены' in dialog._notch_status.text()
    assert dialog.shutdown()
    dialog.close()
