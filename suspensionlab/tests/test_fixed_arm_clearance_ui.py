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


def test_drafts_follow_pairs_and_block_save_and_suggestion_until_resolved(qtbot, monkeypatch, tmp_path):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    report = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),
                              PairProximity('tube_front', 'housing_front', 0, 1e-6, .25)))
    view._completed(view.generation, report)
    view._minimum.setText('.5')
    assert view._table.item(0, 5).text() == 'Не задано (черновик)'
    view._table.selectRow(1)
    view._minimum.setText('ошибка')
    assert len(view.requirement_drafts()) == 2
    view._table.selectRow(0)
    assert view._minimum.text() == '.5'
    view._commit_requirement()
    assert view.requirements() == {'tube_front|tube_rear': .5}
    assert view.requirement_drafts() == (('tube_front|housing_front', 'ошибка'),)
    assert not view._suggest_button.isEnabled()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    target = tmp_path / 'draft.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    dialog._save_file()
    assert warnings and not target.exists()
    view._start_auto()
    assert view._worker is None and 'черновиков' in view._auto_summary.text()
    view._table.selectRow(1)
    assert view._minimum.text() == 'ошибка'
    view._minimum.setText('1')
    view._commit_requirement()
    assert not view.has_uncommitted_requirement() and view._suggest_button.isEnabled()
    dialog._save_file()
    assert target.exists()
    assert dialog.shutdown()
    dialog.close()


def test_geometry_edit_keeps_draft_and_discard_requires_confirmation(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    report = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),))
    view._completed(view.generation, report)
    view._minimum.setText('bad')
    dialog._radius.setValue(dialog._radius.value() + 1)
    assert view._table.isHidden() and view.requirement_drafts() == (('tube_front|tube_rear', 'bad'),)
    assert view._discard_drafts.isEnabled()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    view._discard_requirement_drafts()
    assert view.has_uncommitted_requirement()
    view._completed(view.generation, report)
    assert view._minimum.text() == 'bad'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    view._discard_requirement_drafts()
    assert not view.has_uncommitted_requirement() and view._minimum.text() == ''
    assert dialog.shutdown()
    dialog.close()


def test_housing_removal_discards_only_its_drafts_and_explains(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=True)
    view = dialog._overlap
    report = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),
                              PairProximity('tube_front', 'housing_front', 0, 1e-6, 1)))
    view._completed(view.generation, report)
    view._minimum.setText('0.5')
    view._table.selectRow(1)
    view._minimum.setText('0.8')
    dialog._remove_housings()
    assert view.requirement_drafts() == (('tube_front|tube_rear', '0.5'),)
    assert 'сброшены' in dialog._housing_status.text()
    view._completed(view.generation, ProximityResult((report.pairs[0],)))
    assert view._minimum.text() == '0.5'
    view._commit_requirement()
    assert view.requirements() == {'tube_front|tube_rear': .5}
    assert dialog.shutdown()
    dialog.close()


def test_draft_change_during_discard_dialog_does_not_discard(qtbot, monkeypatch):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    report = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),))
    view._completed(view.generation, report)
    view._minimum.setText('.5')
    def change_during_question(*args):
        view._minimum.setText('.7')
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', change_during_question)
    view._discard_requirement_drafts()
    assert view.requirement_drafts() == (('tube_front|tube_rear', '.7'),)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    assert dialog.shutdown()
    dialog.close()


def test_open_detects_draft_change_during_file_dialog(qtbot, monkeypatch, tmp_path):
    _, dialog = make_dialog(qtbot, monkeypatch, with_housings=False)
    view = dialog._overlap
    report = ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 1),))
    view._completed(view.generation, report)
    view._minimum.setText('.5')
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    def file_dialog(*args):
        view._minimum.setText('.7')
        return str(tmp_path / 'unused.slarm'), ''
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', file_dialog)
    dialog._open_file()
    assert warnings and 'изменились' in warnings[0]
    assert view.requirement_drafts() == (('tube_front|tube_rear', '.7'),)
    assert dialog.shutdown()
    dialog.close()
