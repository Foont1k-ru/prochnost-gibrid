"""Пользовательский путь владения окном узла через главное окно."""
import threading

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from shiboken6 import isValid

from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow


def _running_process(panel):
    worker = panel._worker
    if worker is None:
        return False
    job = worker.job._job
    with job._lock:
        return job._process is not None and job._process.poll() is None


def test_main_window_owns_joint_reopens_fresh_and_stops_real_workers(qtbot, tmp_path, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller = AppController()
    initial_project = controller.project.to_dict()
    window = MainWindow(controller, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.show()
    window.action_joint_concept.trigger()
    first = window._joint_concept_dialog
    assert first is not None and first.parent() is window
    monkeypatch.setattr(first, 'confirm_close', lambda: True)
    window.action_joint_concept.trigger()
    assert window._joint_concept_dialog is first
    panel = first._three_d
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=45000)
    mesh = panel._view.mesh
    first.hide()
    first.show()
    assert first.isVisible() and not panel._closed and panel._view.mesh is mesh
    first._fields['ball']['outer_radius_mm'].setText('23')
    panel._timer.stop()
    panel._start()
    qtbot.waitUntil(lambda: _running_process(panel), timeout=20000)
    worker = panel._worker
    main_thread = threading.get_ident()
    destroyed = []
    first.destroyed.connect(lambda *_: destroyed.append(threading.get_ident() == main_thread),
                            Qt.ConnectionType.DirectConnection)
    assert first.close() and panel._closed and not worker.isRunning()
    assert window._joint_concept_dialog is None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert destroyed == [True] and not isValid(first)

    window.action_joint_concept.trigger()
    second = window._joint_concept_dialog
    assert second is not None and second is not first and second.parent() is window
    assert second._fields['ball']['outer_radius_mm'].text() != '23' and not second._three_d._closed
    monkeypatch.setattr(second, 'confirm_close', lambda: True)
    second_panel = second._three_d
    second_panel._enable.setChecked(True)
    second_panel._timer.stop()
    second_panel._start()
    qtbot.waitUntil(lambda: _running_process(second_panel), timeout=20000)
    second_worker = second_panel._worker
    assert window.close() and second_panel._closed and not second_worker.isRunning()
    assert controller.project.to_dict() == initial_project


@pytest.mark.parametrize('close_parent', [False, True])
def test_failed_worker_stop_retains_window_until_retry(qtbot, tmp_path, monkeypatch, close_parent):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    window = MainWindow(AppController(), QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.show()
    window.action_joint_concept.trigger()
    dialog = window._joint_concept_dialog
    assert dialog is not None
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    panel = dialog._three_d
    assert panel._is_current is not None and panel._is_current.__self__ is dialog
    panel._enable.setChecked(True)
    panel._timer.stop()
    panel._start()
    qtbot.waitUntil(lambda: _running_process(panel), timeout=20000)
    worker = panel._worker
    original_wait = worker.wait
    monkeypatch.setattr(worker, 'wait', lambda *_args: False)  # Simulate a timeout, not a real hung worker.
    target = window if close_parent else dialog
    assert not target.close()
    assert window.isVisible() and dialog.isVisible() and window._joint_concept_dialog is dialog
    assert isValid(dialog) and panel._closed and panel._view.mesh is None and not panel.can_save()
    assert panel._is_current is not None and panel._is_current.__self__ is dialog
    monkeypatch.setattr(worker, 'wait', original_wait)
    qtbot.waitUntil(lambda: panel._worker is None, timeout=30000)
    assert target.close() and panel._is_current is None
    if not close_parent:
        assert window._joint_concept_dialog is None
        window.close()


def test_declining_main_window_close_keeps_joint_worker_and_window(qtbot, tmp_path, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    window = MainWindow(AppController(), QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.show()
    window.action_joint_concept.trigger()
    dialog = window._joint_concept_dialog
    assert dialog is not None
    monkeypatch.setattr(dialog, 'confirm_close', lambda: False)
    panel = dialog._three_d
    panel._enable.setChecked(True)
    panel._timer.stop()
    panel._start()
    qtbot.waitUntil(lambda: _running_process(panel), timeout=20000)
    worker = panel._worker
    assert not window.close()
    assert window.isVisible() and dialog.isVisible() and window._joint_concept_dialog is dialog
    assert not panel._closed and panel._worker is worker
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    assert window.close() and panel._closed and not worker.isRunning()
