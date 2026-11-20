"""Обзор независимых предложений, подтверждение и повторная проверка."""
import threading
from copy import deepcopy

from PySide6.QtWidgets import QMessageBox
from test_fixed_arm_auto import report
from test_fixed_arm_overlap_all_ui import make_dialog

from suspensionlab.core.cad_fixed_arm_overlap_job import (
    AutoPairResult,
    AutoSuggestionResult,
    PairProximity,
    ProximityResult,
    SuggestionResult,
)
from suspensionlab.ui import fixed_arm_overlap as overlap_ui


def test_auto_review_confirmation_and_recheck(qtbot, monkeypatch):
    base = report()
    rows = list(base.pairs)
    rows[0] = PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1)
    after = ProximityResult(tuple(rows))
    proposal = SuggestionResult('candidate', base, 'joint', 'rear', .5, after)
    calls = []
    class FakeJob:
        def cancel(self):
            pass
        def run_auto(self, doc, requirements):
            calls.append((deepcopy(doc), requirements.copy()))
            if len(calls) == 1:
                entries = (AutoPairResult('tube_front', 'tube_rear', 'candidate', proposal),
                           AutoPairResult('tube_front', 'housing_front', 'requirement_missing'),
                           AutoPairResult('tube_front', 'housing_rear', 'unsupported'),
                           *(AutoPairResult(p.left, p.right, 'no_requirement') for p in base.pairs[3:]))
                return AutoSuggestionResult(base, entries)
            entries = tuple(AutoPairResult(p.left, p.right, 'satisfied' if i == 0 else 'no_requirement')
                            for i, p in enumerate(after.pairs))
            return AutoSuggestionResult(after, entries)
    monkeypatch.setattr(overlap_ui, 'FixedArmOverlapJob', FakeJob)
    controller, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    project = deepcopy(controller.project.to_dict())
    view.set_requirements({'tube_front|tube_rear': .5}, housings=True)
    view._start_auto()
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert len(calls) == 1 and view._table.rowCount() == 6
    assert view._table.item(0, 7).text() == 'Есть предложение'
    assert view._table.item(1, 7).text() == 'Пересечение: задайте минимум'
    assert view._table.item(2, 7).text() == 'Нет поддержанного реза'
    assert view._apply_button.isEnabled() and dialog._tube_joint_values() is None
    view._table.selectRow(1)
    assert not view._apply_button.isEnabled()
    view._table.selectRow(0)
    assert view._apply_button.isEnabled() and 'зазор выбранной пары' in view._suggest_status.text()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.No)
    view._confirm_suggestion()
    assert len(calls) == 1 and dialog._tube_joint_values() is None
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    view._confirm_suggestion()
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert len(calls) == 2 and dialog._tube_joint_values() == {'target': 'rear', 'radial_clearance_mm': .5}
    assert view._table.item(0, 7).text() == 'Выполнено' and not view._apply_button.isEnabled()
    assert calls[0][1] == calls[1][1] == {'tube_front|tube_rear': .5}
    assert controller.project.to_dict() == project
    dialog._undo_trim()
    assert view._table.isHidden() and dialog._tube_joint_values() is None
    assert dialog.shutdown()
    dialog.close()


def test_auto_cancel_drops_late_results_and_invalidates_on_edit(qtbot, monkeypatch):
    started = threading.Event()
    class SlowJob:
        def __init__(self):
            self.stopped = threading.Event()
        def cancel(self):
            self.stopped.set()
        def run_auto(self, doc, requirements):
            started.set()
            self.stopped.wait(5)
            p = PairProximity('tube_front', 'tube_rear', 1, 1e-6, 0)
            return AutoSuggestionResult(ProximityResult((p,)), (AutoPairResult(p.left, p.right, 'requirement_missing'),))
    monkeypatch.setattr(overlap_ui, 'FixedArmOverlapJob', SlowJob)
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    view._start_auto()
    assert started.wait(2) and view._cancel_button.isEnabled()
    view._cancel_check()
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert view._table.isHidden() and 'отменён' in view._status.text()
    assert view._auto_button.isEnabled()
    view._start_auto()
    dialog._radius.setValue(dialog._radius.value() + 1)
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert view._table.isHidden() and not view._auto_results
    assert dialog.shutdown()
    dialog.close()


def test_auto_never_discards_uncommitted_requirement(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    p = PairProximity('tube_front', 'tube_rear', 1, 1e-6, 0)
    view._completed(view.generation, ProximityResult((p,)))
    view._minimum.setText('.5')
    view._start_auto()
    assert view._worker is None and view._minimum.text() == '.5'
    assert 'Сначала нажмите' in view._auto_summary.text()
    assert dialog.shutdown()
    dialog.close()


def test_real_auto_applies_only_after_confirmation_and_rechecks(qtbot, monkeypatch):
    import pytest

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    view.set_requirements({'tube_front|tube_rear': 0}, housings=False)
    view._start_auto()
    qtbot.waitUntil(lambda: view._worker is None, timeout=120000)
    assert view._table.item(0, 7).text() == 'Есть предложение', view._auto_summary.text()
    assert dialog._tube_joint_values() is None and view._apply_button.isEnabled()
    view._confirm_suggestion()
    qtbot.waitUntil(lambda: view._worker is None, timeout=120000)
    assert dialog._tube_joint_values()['radial_clearance_mm'] == 0
    assert view._table.item(0, 7).text() == 'Выполнено'
    assert not view._apply_button.isEnabled() and dialog._trim_undo.isEnabled()
    assert dialog.shutdown()
    dialog.close()


def test_auto_confirmation_rejects_geometry_or_requirement_changes(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    base = ProximityResult((PairProximity('tube_front', 'tube_rear', 1, 1e-6, 0),))
    after = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),))
    candidate = SuggestionResult('candidate', base, 'joint', 'rear', .5, after)
    view.set_requirements({'tube_front|tube_rear': .5}, housings=False)
    result = AutoSuggestionResult(base, (AutoPairResult('tube_front', 'tube_rear', 'candidate', candidate),))
    view._completed(view.generation, result)
    assert view._apply_button.isEnabled()
    def change_requirement(*args):
        view.set_requirements({'tube_front|tube_rear': 1}, housings=False)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', change_requirement)
    view._confirm_suggestion()
    assert dialog._tube_joint_values() is None and not view._auto_results
    assert view._table.columnCount() == 7 and not view._apply_button.isEnabled()
    view.set_requirements({'tube_front|tube_rear': .5}, housings=False)
    view._completed(view.generation, result)
    def change_geometry(*args):
        dialog._radius.setValue(dialog._radius.value() + 1)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', change_geometry)
    view._confirm_suggestion()
    assert dialog._tube_joint_values() is None and view._table.isHidden()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    assert dialog.shutdown()
    dialog.close()


def test_auto_report_is_not_saved_or_restored(qtbot, monkeypatch, tmp_path):
    import json

    from PySide6.QtWidgets import QFileDialog

    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    base = ProximityResult((PairProximity('tube_front', 'tube_rear', 1, 1e-6, 0),))
    after = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),))
    candidate = SuggestionResult('candidate', base, 'joint', 'rear', .5, after)
    view.set_requirements({'tube_front|tube_rear': .5}, housings=False)
    view._completed(view.generation, AutoSuggestionResult(base, (AutoPairResult('tube_front', 'tube_rear',
                                                                               'candidate', candidate),)))
    assert view._apply_button.isEnabled()
    path = tmp_path / 'auto.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), ''))
    dialog._save_file()
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['geometry']['clearance_requirements_mm'] == {'tube_front|tube_rear': .5}
    assert 'candidate' not in json.dumps(saved) and dialog._tube_joint_values() is None
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (str(path), ''))
    dialog._open_file()
    assert view.requirements() == {'tube_front|tube_rear': .5}
    assert not view._auto_results and view._table.isHidden() and not view._apply_button.isEnabled()
    assert dialog.shutdown()
    dialog.close()
