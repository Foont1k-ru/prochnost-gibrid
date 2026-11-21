"""Актуальность отчёта, повторная проверка и сохранение выбранных подрезок."""
import pytest
from PySide6.QtWidgets import QFileDialog
from test_fixed_arm_overlap_all_ui import make_dialog

from suspensionlab.core.cad_fixed_arm_overlap_job import PairProximity, ProximityResult


def wait_result(qtbot, view, expected_count):
    assert view._distance_button.isEnabled()
    view._start_proximity()
    assert view._worker is not None and not view._distance_button.isEnabled()
    qtbot.waitUntil(lambda: view._worker is None, timeout=60000)
    assert view._table.rowCount() == expected_count and not view._table.isHidden(), view._status.text()


@pytest.mark.parametrize(('with_housings', 'count'), [(False, 1), (True, 6)])
def test_real_report_invalidates_on_edit_and_can_recheck(qtbot, monkeypatch, with_housings, count):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_dialog(qtbot, monkeypatch, with_housings=with_housings)
    view = dialog._overlap
    before = controller.project.to_dict()
    wait_result(qtbot, view, count)
    assert 'не проверка движения' in view._status.text()
    assert view._table.item(0, 0).text() == 'Передняя труба — Задняя труба'
    assert view._table.item(0, 4).text() != 'Ошибка — не проверено'
    token = view.generation
    dialog._radius.setValue(dialog._radius.value() + 1)
    assert view._table.isHidden() and view._table.rowCount() == 0
    view._completed(token, ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 99),)))
    assert view._table.isHidden()
    wait_result(qtbot, view, count)
    assert controller.project.to_dict() == before
    assert dialog.shutdown()
    dialog.close()


def test_save_reopen_joint_notch_then_rebuild_and_check(qtbot, monkeypatch, tmp_path):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    dialog._notch_checks['front'].setChecked(True)
    dialog._notch_clearances['front'].setText('0.5')
    dialog._tube_joint.setCurrentIndex(dialog._tube_joint.findData('rear'))
    dialog._joint_clearance.setText('0.5')
    wait_result(qtbot, view, 6)
    path = tmp_path / 'trim.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    assert path.exists()
    dialog._tube_joint.setCurrentIndex(0)
    assert view._table.isHidden()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert dialog._tube_joint_values() == {'target': 'rear', 'radial_clearance_mm': 0.5}
    assert dialog._notch_values() == {'front': 0.5}
    assert view._table.isHidden()
    wait_result(qtbot, view, 6)
    assert dialog.shutdown()
    dialog.close()


def test_pair_failures_are_not_reported_as_clearance(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    view._completed(view.generation, ProximityResult((PairProximity('tube_front', 'tube_rear', None, None, None),)))
    assert 'ошибок: 1' in view._status.text()
    assert view._table.item(0, 1).text() == '—'
    assert view._table.item(0, 4).text() == 'Ошибка — не проверено'
    view._completed(view.generation, ProximityResult((PairProximity('tube_front', 'tube_rear', 1e-7, 1e-6, 2),)))
    assert view._table.item(0, 1).text() == '—'
    assert 'Возможное малое пересечение' in view._table.item(0, 4).text()
    assert dialog.shutdown()
    dialog.close()


def test_cancelled_proximity_cannot_apply_late_report(qtbot, monkeypatch):
    import threading

    from suspensionlab.ui import fixed_arm_overlap as overlap_ui

    class SlowJob:
        def __init__(self):
            self.stopped = threading.Event()

        def cancel(self):
            self.stopped.set()

        def run_proximity(self, _document):
            self.stopped.wait(timeout=5)
            return ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 99),))

    monkeypatch.setattr(overlap_ui, 'FixedArmOverlapJob', SlowJob)
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    view._start_proximity()
    assert view._worker is not None
    dialog._radius.setValue(dialog._radius.value() + 1)
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert view._table.isHidden() and view._table.rowCount() == 0
    assert view._distance_button.isEnabled() and 'не запускалась' in view._status.text()
    assert dialog.shutdown()
    dialog.close()
