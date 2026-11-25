"""Пользовательский анализ независимого рычага и защита от устаревших ответов."""
from copy import deepcopy
from threading import Event

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from test_free_arm_housing_io import make_draft
from test_free_arm_tube_joint_ui import editor, select_joint

from suspensionlab.core.cad_fixed_arm_overlap_job import PairProximity, ProximityResult
from suspensionlab.model.free_arm_io import write_free_arm
from suspensionlab.ui import free_arm_proximity as ui


class SlowJob:
    instances = []

    def __init__(self):
        self.started, self.released = Event(), Event()
        self.cancelled = False
        self.document = None
        self.__class__.instances.append(self)

    def cancel(self):
        self.cancelled = True

    def run_proximity(self, document):
        self.document = deepcopy(document)
        self.started.set()
        self.released.wait(10)
        return ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 99),))


@pytest.fixture
def slow(monkeypatch):
    SlowJob.instances = []
    monkeypatch.setattr(ui, 'FixedArmOverlapJob', SlowJob)
    return SlowJob.instances


def show_analysis(dialog):
    view = dialog._proximity
    dialog._tabs.setCurrentWidget(dialog._proximity_scroll)
    return view


def start_slow(qtbot, view, instances):
    view._start()
    assert view._worker is not None
    job = instances[-1]
    qtbot.waitUntil(job.started.is_set, timeout=5000)
    return job


@pytest.mark.parametrize(('kind', 'count'), [('plain', 1), ('inner', 6), ('ball', 10), ('joint', 6)])
def test_real_user_path_and_recheck(qtbot, monkeypatch, kind, count):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, base = editor(qtbot, monkeypatch, inner=kind != 'plain')
    if kind == 'ball':
        dialog._set_housing_fields(make_draft().housing)
        dialog.apply_fields()
    if kind == 'joint':
        select_joint(dialog)
    view = show_analysis(dialog)
    assert dialog._tabs.currentWidget().widget() is view
    assert not dialog._cad._enable.isChecked()  # The independent analysis builds its own CAD.
    before = deepcopy(dialog._document_for(dialog.draft, dialog.housing))
    assert view._button.isEnabled()
    qtbot.mouseClick(view._button, Qt.MouseButton.LeftButton)
    assert view._worker is not None and view._cancel_button.isEnabled()
    qtbot.waitUntil(lambda: view._worker is None, timeout=60000)
    assert view._table.rowCount() == count and not view._table.isHidden(), view._status.text()
    assert view._table.item(0, 0).text() == 'Передняя труба — Задняя труба'
    assert 'ошибок: 0' in view._status.text()
    assert dialog._document_for(dialog.draft, dialog.housing) == before
    assert dialog.draft == base.arm
    previous = view.generation
    dialog._fields['front_X'].setText('2')
    assert not view._button.isEnabled() and view._table.isHidden() and view._table.rowCount() == 0
    view._completed(previous, ProximityResult((PairProximity('tube_front', 'tube_rear', 0, 1e-6, 99),)))
    assert view._table.isHidden()
    dialog._restore_draft()
    assert view._button.isEnabled() and view._table.isHidden()
    view._start()
    qtbot.waitUntil(lambda: view._worker is None, timeout=60000)
    assert view._table.rowCount() == count and not view._table.isHidden()
    dialog.close()


def test_cancel_ignores_late_result_and_can_repeat(qtbot, monkeypatch, slow):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    view = show_analysis(dialog)
    job = start_slow(qtbot, view, slow)
    view._cancel()
    assert job.cancelled and view._table.isHidden() and not view._button.isEnabled()
    job.released.set()
    qtbot.waitUntil(lambda: view._worker is None, timeout=5000)
    assert view._table.rowCount() == 0 and 'отменена' in view._status.text() and view._button.isEnabled()
    second = start_slow(qtbot, view, slow)
    second.released.set()
    qtbot.waitUntil(lambda: view._worker is None, timeout=5000)
    assert view._table.rowCount() == 1 and view._table.item(0, 1).text() == '99'
    dialog.close()


@pytest.mark.parametrize('change', ['form', 'accepted', 'restore', 'open', 'undo'])
def test_change_cancels_running_job_and_discards_late_result(qtbot, monkeypatch, slow, tmp_path, change):
    dialog, base = editor(qtbot, monkeypatch, inner=False)
    if change == 'undo':
        select_joint(dialog)
    view = show_analysis(dialog)
    job = start_slow(qtbot, view, slow)
    if change == 'form':
        dialog._fields['front_X'].setText('2')
    elif change == 'accepted':
        dialog._fields['front_X'].setText('2')
        dialog.apply_fields()
    elif change == 'restore':
        dialog._fields['front_X'].setText('2')
        dialog._restore_draft()
    elif change == 'open':
        path = write_free_arm(tmp_path / 'arm.slarm', base.arm)
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
        dialog._open_file()
    else:
        dialog._undo_trim()
    assert job.cancelled and view._table.isHidden() and not view._button.isEnabled()
    job.released.set()
    qtbot.waitUntil(lambda: view._worker is None, timeout=5000)
    assert view._table.rowCount() == 0 and view._table.isHidden()
    assert view._button.isEnabled() == (change != 'form')
    if change in ('restore', 'open', 'undo'):
        assert dialog.draft == base.arm
    dialog.close()


def test_failed_pairs_and_small_overlap_are_not_claimed_as_distance(qtbot, monkeypatch):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    view = show_analysis(dialog)
    for pair, label in ((PairProximity('tube_front', 'tube_rear', None, None, None), 'Ошибка'),
                        (PairProximity('tube_front', 'tube_rear', 1e-7, 1e-6, 3), 'Малое пересечение')):
        view._completed(view.generation, ProximityResult((pair,)))
        assert view._table.item(0, 1).text() == '—'
        assert label in view._table.item(0, 4).text()
    view._failed(view.generation, 'timeout')
    assert view._table.isHidden() and 'превышено время' in view._status.text()
    dialog.close()


def test_close_stops_worker_and_ignores_result(qtbot, monkeypatch, slow):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    view = show_analysis(dialog)
    job = start_slow(qtbot, view, slow)
    # Release the child while shutdown waits; it returns a late successful report.
    job.released.set()
    assert dialog.shutdown()
    assert job.cancelled and view._closed and view._is_current is None
    qtbot.waitUntil(lambda: view._worker is None, timeout=5000)
    assert view._table.isHidden() and view._table.rowCount() == 0 and not view._button.isEnabled()
    dialog.close()


def test_buttons_fit_and_are_reachable(qtbot, monkeypatch):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    view = show_analysis(dialog)
    scroll = dialog._tabs.currentWidget()
    for button in (view._button, view._cancel_button):
        scroll.ensureWidgetVisible(button)
        qtbot.waitUntil(lambda button=button: button.width() >= button.sizeHint().width())
        assert button.fontMetrics().horizontalAdvance(button.text()) <= button.width()
        assert scroll.viewport().rect().contains(button.mapTo(scroll.viewport(), button.rect().topLeft()))
        assert scroll.viewport().rect().contains(button.mapTo(scroll.viewport(), button.rect().bottomRight()))
    dialog.close()


def test_projection_draft_cancels_report_until_session_closed(qtbot, monkeypatch, slow):
    dialog, _ = editor(qtbot, monkeypatch, inner=False, bent=('front',))
    view = show_analysis(dialog)
    job = start_slow(qtbot, view, slow)
    dialog._tabs.setCurrentWidget(dialog._projections[0])
    dialog._projection_point(dialog._projections[0], 'bend_front')
    assert dialog._projection_session is not None and job.cancelled and view._document is None
    job.released.set()
    qtbot.waitUntil(lambda: view._worker is None, timeout=5000)
    assert view._table.isHidden() and not view._button.isEnabled()
    dialog._close_projection_session()
    assert view._button.isEnabled() and view._table.isHidden()
    dialog.close()


def test_inline_draft_blocks_analysis_until_closed(qtbot, monkeypatch, slow):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, _ = editor(qtbot, monkeypatch, inner=False, bent=('front',))
    view = show_analysis(dialog)
    job = start_slow(qtbot, view, slow)
    dialog._tabs.setCurrentWidget(dialog._cad)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    dialog._open_inline_sketch('front')
    assert dialog._inline_session is not None and job.cancelled and view._document is None
    job.released.set()
    qtbot.waitUntil(lambda: view._worker is None, timeout=5000)
    view._start()
    assert view._worker is None and view._table.isHidden()
    dialog._close_inline_sketch()
    assert view._button.isEnabled() and view._table.isHidden()
    dialog.close()


def test_shutdown_timeout_preserves_worker_until_retry(qtbot, monkeypatch, slow):
    dialog, _ = editor(qtbot, monkeypatch, inner=False)
    view = show_analysis(dialog)
    job = start_slow(qtbot, view, slow)
    worker = view._worker
    assert worker is not None
    with monkeypatch.context() as patch:
        patch.setattr(worker, 'wait', lambda *_: False)
        assert not dialog.close()
        assert dialog.isVisible() and view._worker is worker and view._closed and job.cancelled
        assert 'закрыть окно снова' in view._status.text()
    job.released.set()
    assert dialog.close()
    qtbot.waitUntil(lambda: view._worker is None, timeout=5000)
    assert view._is_current is None and view._table.isHidden()


def test_menu_start_analysis_does_not_modify_project(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from test_arm_workspace_start_ui import choose
    from test_free_arm_ui import fill

    from suspensionlab.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    project = deepcopy(window.controller.project.to_dict())
    choose(qtbot, window, 'independent')
    dialog = window._free_arm_dialog
    assert dialog is not None
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    fill(dialog)
    dialog.apply_fields()
    view = show_analysis(dialog)
    qtbot.mouseClick(view._button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: view._worker is None, timeout=60000)
    assert view._table.rowCount() == 1 and not view._table.isHidden(), view._status.text()
    assert window.controller.project.to_dict() == project
    dialog.close()
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.close()
