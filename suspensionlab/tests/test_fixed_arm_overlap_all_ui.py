"""Попарный отчёт не выдаёт зазоры и не показывает устаревшие результаты."""
import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox
from test_fixed_arm_housings import housings

from suspensionlab.core.cad_fixed_arm_overlap_job import PairOverlap, PairwiseResult
from suspensionlab.model.templates import load_template
from suspensionlab.ui import fixed_arm_overlap as overlap_ui
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_housings_dialog import FixedArmHousingsDialog
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def make_dialog(qtbot, monkeypatch, *, with_housings):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.show()
    dialog._capture_snapshot()
    if with_housings:
        def accept(modal):
            modal.result_values = housings()
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(FixedArmHousingsDialog, 'exec', accept)
        dialog._edit_housings()
    dialog._tabs.setCurrentIndex(4)
    dialog._cad_tools.setCurrentIndex(2)
    return controller, dialog


@pytest.mark.parametrize(('with_housings', 'count'), [(False, 1), (True, 6)])
def test_all_pairs_ui_real_cad_and_invalidation(qtbot, monkeypatch, with_housings, count):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_dialog(qtbot, monkeypatch, with_housings=with_housings)
    original = controller.project.to_dict()
    view = dialog._overlap
    assert view._all_button.isEnabled()
    qtbot.mouseClick(view._all_button, Qt.MouseButton.LeftButton)
    assert view._worker is not None and not view._all_button.isEnabled()
    qtbot.waitUntil(lambda: view._worker is None, timeout=60000)
    assert view._table.rowCount() == count and not view._table.isHidden()
    assert 'не означает наличие зазора' in view._status.text()
    assert view._table.item(0, 0).text() == 'Передняя труба — Задняя труба'
    if with_housings:
        assert view._table.item(5, 0).text() == 'Передний корпус — Задний корпус'
    assert controller.project.to_dict() == original
    token = view.generation
    dialog._radius.setValue(dialog._radius.value() + 1)
    assert view._table.rowCount() == 0 and view._table.isHidden()
    view._completed(token, PairwiseResult((PairOverlap('tube_front', 'tube_rear', 99, 1e-6),)))
    assert view._table.rowCount() == 0 and '99' not in view._status.text()
    assert dialog.shutdown()
    dialog.close()


def test_failed_and_stale_results_do_not_leave_a_table(qtbot, monkeypatch):
    controller, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    result = PairwiseResult((PairOverlap('tube_front', 'tube_rear', 99, 1e-6),))
    view._completed(view.generation, result)
    assert view._table.rowCount() == 1
    view._failed(view.generation, 'failed')
    assert view._table.rowCount() == 0 and view._table.isHidden()
    assert 'Достоверного результата нет' in view._status.text()
    controller.project.front.hardpoints['lbj'].x += 1
    view._completed(view.generation, result)
    assert view._table.rowCount() == 0 and view._table.isHidden()
    assert 'устарел' in view._status.text()
    assert dialog.shutdown()
    dialog.close()


def test_cancelled_check_cannot_apply_late_result(qtbot, monkeypatch):
    monkeypatch.setattr(overlap_ui, 'FixedArmOverlapJob', SlowJob)
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    view._start_all()
    assert view._worker is not None
    dialog._radius.setValue(dialog._radius.value() + 1)
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert view._table.rowCount() == 0 and view._table.isHidden()
    assert 'не запускалась' in view._status.text() and view._all_button.isEnabled()
    assert dialog.shutdown()
    dialog.close()


class SlowJob:
    def __init__(self):
        self.stopped = threading.Event()

    def cancel(self):
        self.stopped.set()

    def run_all(self, _document):
        self.stopped.wait(timeout=5)
        # A late completed signal must still be discarded even if cancel raced.
        return PairwiseResult((PairOverlap('tube_front', 'tube_rear', 99, 1e-6),))
