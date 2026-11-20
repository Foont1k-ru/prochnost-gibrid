"""Предложение не меняет геометрию до подтверждения и исчезает при правке."""
from PySide6.QtWidgets import QFileDialog, QMessageBox
from test_fixed_arm_overlap_all_ui import make_dialog

from suspensionlab.core.cad_fixed_arm_overlap_job import PairProximity, ProximityResult, SuggestionResult
from suspensionlab.ui import fixed_arm_overlap as overlap_ui


def test_proposal_requires_input_confirmation_and_keeps_project(qtbot, monkeypatch, tmp_path):
    baseline = ProximityResult((PairProximity('tube_front', 'tube_rear', 10, 1e-6, 0),))
    after = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),))
    class FakeJob:
        def cancel(self):
            pass
        def run_suggestion(self, doc, left, right, minimum, *, requirements):
            assert requirements == {'tube_front|tube_rear': 0.5}
            assert (left, right, minimum) == ('tube_front', 'tube_rear', 0.5)
            return SuggestionResult('candidate', baseline, 'joint', 'rear', 0.5, after)
    monkeypatch.setattr(overlap_ui, 'FixedArmOverlapJob', FakeJob)
    controller, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    original_project = controller.project.to_dict()
    view._completed(view.generation, baseline)
    assert not view._suggest_button.isEnabled()
    view._minimum.setText('0,5')
    assert not view._suggest_button.isEnabled() and view._set_minimum.isEnabled()
    view._commit_requirement()
    assert view._suggest_button.isEnabled() and 'не выполнено' in view._suggest_status.text().lower()
    view._start_suggestion()
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert view._apply_button.isEnabled() and 'Предложение' in view._suggest_status.text()
    assert dialog._tube_joint_values() is None
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    view._confirm_suggestion()
    assert dialog._tube_joint_values() is None
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    view._confirm_suggestion()
    assert dialog._tube_joint_values() == {'target': 'rear', 'radial_clearance_mm': 0.5}
    assert view._table.isHidden() and not view._apply_button.isEnabled()
    assert dialog._trim_undo.isEnabled()
    dialog._undo_trim()
    assert dialog._tube_joint_values() is None
    assert dialog._trim_redo.isEnabled()
    dialog._redo_trim()
    assert dialog._tube_joint_values() == {'target': 'rear', 'radial_clearance_mm': 0.5}
    path = tmp_path / 'candidate.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    assert path.exists()
    dialog._tube_joint.setCurrentIndex(0)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert dialog._tube_joint_values() == {'target': 'rear', 'radial_clearance_mm': 0.5}
    assert not dialog._trim_undo.isEnabled() and view._table.isHidden()
    assert controller.project.to_dict() == original_project
    assert dialog.shutdown()
    dialog.close()


def test_changing_requirement_discards_proposal(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    base = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),))
    view._completed(view.generation, base)
    view._minimum.setText('0.5')
    view._commit_requirement()
    assert 'выполнено' in view._suggest_status.text().lower()
    view._suggestion = SuggestionResult('candidate', base, 'joint', 'rear', .5, base)
    view._apply_button.setEnabled(True)
    view._minimum.setText('0.9')
    assert view._suggestion is None and not view._apply_button.isEnabled()
    view._minimum.setText('nan')
    assert not view._suggest_button.isEnabled() and 'не принят' in view._suggest_status.text()
    assert dialog.shutdown()
    dialog.close()


def test_manual_trim_history_branching_and_snapshot_reset(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    dialog._notch_checks['front'].setChecked(True)
    dialog._notch_clearances['front'].setText('0.5')
    assert dialog._notch_values() == {'front': 0.5}
    dialog._undo_trim()
    assert dialog._notch_checks['front'].isChecked() and dialog._notch_clearances['front'].text() == ''
    dialog._redo_trim()
    assert dialog._notch_values() == {'front': 0.5}
    dialog._undo_trim()
    dialog._notch_clearances['front'].setText('1')
    assert not dialog._trim_redo.isEnabled() and dialog._notch_values() == {'front': 1}
    dialog._remove_housings()
    assert not dialog._trim_undo.isEnabled() and not dialog._trim_redo.isEnabled()
    assert dialog._notch_values() is None
    assert dialog.shutdown()
    dialog.close()


def test_closest_markers_are_cleared_after_geometry_edit(qtbot, monkeypatch):
    import pytest

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    view = dialog._overlap
    points = ((0., 1., 2.), (0., 2., 2.))
    pair = PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1, points, 2)
    view._completed(view.generation, ProximityResult((pair,)))
    assert dialog._cad._view._markers == points
    dialog._radius.setValue(dialog._radius.value() + 1)
    assert dialog._cad._view._markers == () and view._table.isHidden()
    assert dialog.shutdown()
    dialog.close()


def test_requirement_never_follows_selection_to_another_pair(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    report = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),
                              PairProximity('tube_front', 'housing_front', 0, 1e-6, 1)))
    view._completed(view.generation, report)
    view._minimum.setText('0.5')
    view._commit_requirement()
    assert 'выполнено' in view._suggest_status.text().lower()
    view._table.selectRow(1)
    assert view._minimum.text() == '' and not view._suggest_button.isEnabled()
    view._table.selectRow(0)
    assert view._minimum.text() == '0.5' and view._suggest_button.isEnabled()
    assert dialog.shutdown()
    dialog.close()


def test_stale_confirmation_cannot_apply_candidate(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    base = ProximityResult((PairProximity('tube_front', 'tube_rear', 10, 1e-6, 0),))
    after = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),))
    view._completed(view.generation, base)
    view._minimum.setText('0.5')
    view._show_suggestion(SuggestionResult('candidate', base, 'joint', 'rear', .5, after))
    def changed(*args):
        dialog._radius.setValue(dialog._radius.value() + 1)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', changed)
    view._confirm_suggestion()
    assert dialog._tube_joint_values() is None and not view._apply_button.isEnabled()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    assert dialog.shutdown()
    dialog.close()


def test_real_worker_suggests_zero_without_applying_until_confirmation(qtbot, monkeypatch):
    import pytest

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    view._start_proximity()
    qtbot.waitUntil(lambda: view._worker is None, timeout=60000)
    view._minimum.setText('0')
    view._commit_requirement()
    assert view._suggest_button.isEnabled()
    view._start_suggestion()
    qtbot.waitUntil(lambda: view._worker is None, timeout=90000)
    assert view._suggestion is not None and view._apply_button.isEnabled(), view._suggest_status.text()
    assert dialog._tube_joint_values() is None
    view._confirm_suggestion()
    assert dialog._tube_joint_values()['radial_clearance_mm'] == 0
    assert dialog._trim_undo.isEnabled()
    dialog._undo_trim()
    assert dialog._tube_joint_values() is None
    assert dialog.shutdown()
    dialog.close()
