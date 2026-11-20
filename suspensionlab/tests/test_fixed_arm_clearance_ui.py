"""Явные требования пары, сохранение и отсутствие устаревших заключений."""
import json

from PySide6.QtWidgets import QFileDialog, QMessageBox
from test_fixed_arm_overlap_all_ui import make_dialog

from suspensionlab.core.cad_fixed_arm_overlap_job import PairProximity, ProximityResult


def test_explicit_per_pair_save_reopen_and_recheck(qtbot, monkeypatch, tmp_path):
    controller, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    original = controller.project.to_dict()
    report = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),
                              PairProximity('tube_front', 'housing_front', 0, 1e-6, .25)))
    view._completed(view.generation, report)
    assert view._table.item(0, 5).text() == 'Не задано'
    assert view._table.item(1, 6).text() == 'Не задано'
    view._minimum.setText('0.5')
    assert view.requirements() == {} and not view._suggest_button.isEnabled()
    view._commit_requirement()
    assert view.requirements() == {'tube_front|tube_rear': 0.5}
    assert view._table.item(0, 6).text() == 'Выполнено на снимке'
    view._table.selectRow(1)
    assert view._minimum.text() == ''
    view._minimum.setText('1')
    view._commit_requirement()
    assert view._table.item(1, 6).text() == 'Не выполнено'
    assert len(view.requirements()) == 2
    path = tmp_path / 'with-requirements.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    assert json.loads(path.read_text(encoding='utf-8'))['version'] == '5'
    dialog._radius.setValue(dialog._radius.value() + 1)
    assert view._table.isHidden() and len(view.requirements()) == 2
    assert 'не проверены' in view._suggest_status.text()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert len(view.requirements()) == 2 and view._table.isHidden()
    view._completed(view.generation, report)
    assert view._table.item(0, 6).text() == 'Выполнено на снимке'
    assert view._table.item(1, 6).text() == 'Не выполнено'
    view._table.selectRow(1)
    assert view._minimum.text() == '1.0'
    view._remove_requirement()
    assert view._table.item(1, 6).text() == 'Не задано'
    assert view.requirements() == {'tube_front|tube_rear': .5}
    assert controller.project.to_dict() == original
    assert dialog.shutdown()
    dialog.close()


def test_uncommitted_input_cannot_be_silently_saved(qtbot, monkeypatch, tmp_path):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    view._completed(view.generation, ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),)))
    view._minimum.setText('not a number')
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(tmp_path / 'bad.slarm'), ''))
    dialog._save_file()
    assert warnings and not (tmp_path / 'bad.slarm').exists()
    assert view._minimum.text() == 'not a number'
    view._minimum.clear()
    assert dialog.shutdown()
    dialog.close()


def test_housing_change_clears_only_requirements_involving_housings(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    view.set_requirements({'tube_front|tube_rear': .5, 'tube_front|housing_front': 0}, housings=True)
    dialog._remove_housings()
    assert view.requirements() == {'tube_front|tube_rear': .5}
    assert 'требования' in dialog._housing_status.text()
    assert dialog.shutdown()
    dialog.close()


def test_numerical_tolerance_and_errors_do_not_claim_success():
    from suspensionlab.ui.fixed_arm_overlap import _requirement_status

    def pair(distance, volume=0):
        return PairProximity('tube_front', 'tube_rear', volume, 1e-6, distance)
    assert _requirement_status(pair(10), None) == 'Не задано'
    assert _requirement_status(pair(0), 0) == '0: касание допускается'
    assert _requirement_status(pair(0, 1e-7), 0) == 'Не проверено'
    assert _requirement_status(PairProximity('tube_front', 'tube_rear', None, None, None), 1) == 'Не проверено'
    assert _requirement_status(pair(0, 1), 0) == 'Не выполнено: пересечение'
    assert _requirement_status(pair(.5), 1) == 'Не выполнено'
    assert _requirement_status(pair(1), 1) == 'У границы: не подтверждено'
    assert _requirement_status(pair(1.001), 1) == 'Выполнено на снимке'


def test_changing_saved_requirements_cancels_inflight_proposal(qtbot, monkeypatch):
    import threading

    from suspensionlab.core.cad_fixed_arm_overlap_job import SuggestionResult
    from suspensionlab.ui import fixed_arm_overlap as overlap_ui

    base = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),))
    class SlowJob:
        def __init__(self):
            self.stopped = threading.Event()
        def cancel(self):
            self.stopped.set()
        def run_suggestion(self, *args, **kwargs):
            self.stopped.wait(timeout=5)
            return SuggestionResult('candidate', base, 'joint', 'rear', .5, base)
    monkeypatch.setattr(overlap_ui, 'FixedArmOverlapJob', SlowJob)
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    view._completed(view.generation, base)
    view._minimum.setText('.5')
    view._commit_requirement()
    view._start_suggestion()
    assert view._worker is not None
    view.set_requirements({'tube_front|tube_rear': 2}, housings=False)
    qtbot.waitUntil(lambda: view._worker is None, timeout=10000)
    assert view._suggestion is None and not view._apply_button.isEnabled()
    assert view.requirements() == {'tube_front|tube_rear': 2}
    assert dialog.shutdown()
    dialog.close()
