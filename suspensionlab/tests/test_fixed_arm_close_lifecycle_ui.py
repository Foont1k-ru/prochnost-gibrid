"""Закрытие основного окна с настоящими дочерними CAD-процессами."""
import gc

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QMessageBox

from suspensionlab.core.cad_fixed_arm_overlap_job import OverlapResult
from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)


def _process_of(worker, *, overlap=False):
    job = worker.job if overlap else worker.job._job
    with job._lock:
        process = job._process
        return process if process is not None and process.poll() is None else None


def _start_cad(panel):
    panel._enable.setChecked(True)
    panel._timer.stop()
    panel._start()
    assert panel._worker is not None
    return panel._worker


def test_cancel_then_close_main_window_stops_all_real_cad_jobs(qtbot, monkeypatch, tmp_path):
    controller = AppController()
    controller.project = load_template('ring')
    original = controller.project.to_dict()
    window = MainWindow(controller, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.No)
    try:
        window._open_fixed_arm_skeleton()
        fixed = window._fixed_arm_skeleton_dialog
        fixed._capture_snapshot()
        assert fixed.snapshot is not None and fixed._state() != fixed._saved_state
        window._open_joint_concept()
        joint = window._joint_concept_dialog
        fixed_worker = _start_cad(fixed._cad)
        joint_worker = _start_cad(joint._three_d)
        fixed._overlap._start_all()
        overlap_worker = fixed._overlap._worker
        assert overlap_worker is not None
        qtbot.waitUntil(lambda: all((_process_of(fixed_worker), _process_of(joint_worker),
                                     _process_of(overlap_worker, overlap=True))), timeout=30000)
        processes = (_process_of(fixed_worker), _process_of(joint_worker),
                     _process_of(overlap_worker, overlap=True))
        assert all(process is not None for process in processes)
        tokens = fixed._cad.generation, joint._three_d.generation, fixed._overlap.generation

        # Отказ в подтверждении не должен отменить ни одну из работающих задач.
        assert not window.close()
        assert window.isVisible() and fixed.isVisible() and joint.isVisible()
        assert not fixed._cad._closed and not joint._three_d._closed and not fixed._overlap._closed
        assert fixed._cad.generation == tokens[0] and joint._three_d.generation == tokens[1]
        assert fixed._overlap.generation == tokens[2]
        assert not fixed_worker.job._job.is_cancelled() and not joint_worker.job._job.is_cancelled()
        assert not overlap_worker.job._cancelled.is_set()
        assert controller.project.to_dict() == original

        monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)
        assert window.close()
        assert all(not worker.isRunning() for worker in (fixed_worker, joint_worker, overlap_worker))
        assert all(process.poll() is not None for process in processes)
        assert fixed._cad._closed and joint._three_d._closed and fixed._overlap._closed
        assert fixed._cad._view.mesh is None and joint._three_d._view.mesh is None
        assert fixed._overlap._table.rowCount() == 0
        fixed._cad._completed(tokens[0], object())
        joint._three_d._completed(tokens[1], object())
        fixed._overlap._completed(tokens[2], OverlapResult(1., 1.))
        assert fixed._cad._view.mesh is None and joint._three_d._view.mesh is None
        assert fixed._overlap._table.rowCount() == 0
        assert controller.project.to_dict() == original
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()
    finally:
        monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)
        if window.isVisible():
            window.close()


@pytest.mark.parametrize(('opening', 'attribute', 'panel_name'), [
    ('_open_joint_concept', '_joint_concept_dialog', '_three_d'),
    ('_open_arm_concept', '_arm_concept_dialog', '_three_d'),
    ('_open_front_tubes', '_front_tubes_dialog', '_three_d'),
    ('_open_rear_tube', '_rear_tube_dialog', '_three_d'),
    ('_open_fixed_arm_skeleton', '_fixed_arm_skeleton_dialog', '_cad'),
])
def test_close_and_reopen_editor_while_real_cad_is_running(qtbot, monkeypatch, tmp_path,
                                                           opening, attribute, panel_name):
    import threading

    import shiboken6
    from PySide6.QtCore import Qt

    controller = AppController()
    controller.project = load_template('ring')
    if opening == '_open_rear_tube':
        controller.set_axle_type('rear', 'live_axle_coil')
        for code, xyz in {'ll_in_l': (0, 0, 0), 'll_out_l': (100, 100, 0),
                          'll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
            point = controller.project.rear.hardpoints[code]
            point.x, point.y, point.z = xyz
    original = controller.project.to_dict()
    window = MainWindow(controller, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    window.show()
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)
    destroyed_threads = []
    main_thread = threading.get_ident()
    try:
        for _ in range(2):
            getattr(window, opening)()
            dialog = getattr(window, attribute)
            if opening == '_open_fixed_arm_skeleton':
                dialog._capture_snapshot()
            elif opening == '_open_rear_tube':
                dialog._arm.setCurrentIndex(dialog._arm.findData('rear_lower_left'))
            panel = getattr(dialog, panel_name)
            assert panel._document is not None
            dialog.destroyed.connect(lambda *_args: destroyed_threads.append(threading.get_ident()),
                                     Qt.ConnectionType.DirectConnection)
            _start_cad(panel)
            qtbot.waitUntil(lambda panel=panel: panel._ready and panel._worker is None, timeout=60000)
            assert panel._view.mesh is not None
            panel._quality.setCurrentIndex(1)
            panel._timer.stop()
            panel._start()
            worker = panel._worker
            assert worker is not None
            qtbot.waitUntil(lambda worker=worker: _process_of(worker) is not None, timeout=30000)
            process = _process_of(worker)
            assert process is not None
            assert dialog.close()
            assert getattr(window, attribute) is None and panel._closed and not worker.isRunning()
            assert process.poll() is not None and controller.project.to_dict() == original
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert not shiboken6.isValid(dialog)
            assert destroyed_threads[-1] == main_thread
            gc.collect()
        assert len(destroyed_threads) == 2
    finally:
        if window.isVisible():
            window.close()


def test_fixed_editor_confirms_once_before_stopping_real_cad(qtbot, monkeypatch, tmp_path):
    controller = AppController()
    controller.project = load_template('ring')
    window = MainWindow(controller, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()
    window._open_fixed_arm_skeleton()
    dialog = window._fixed_arm_skeleton_dialog
    dialog._capture_snapshot()
    panel = dialog._cad
    worker = _start_cad(panel)
    qtbot.waitUntil(lambda: _process_of(worker) is not None, timeout=30000)
    process = _process_of(worker)
    assert process is not None
    answers = []
    def refuse(*_args):
        answers.append('no')
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, 'question', refuse)
    try:
        assert not dialog.close()
        assert answers == ['no'] and dialog.isVisible() and not panel._closed
        assert not worker.job._job.is_cancelled()
        answers.clear()
        def accept_only_first(*_args):
            answers.append('asked')
            return QMessageBox.StandardButton.Yes if len(answers) == 1 else QMessageBox.StandardButton.No
        monkeypatch.setattr(QMessageBox, 'question', accept_only_first)
        assert dialog.close()
        assert answers == ['asked']
        assert panel._closed and not worker.isRunning() and process.poll() is not None
        assert window._fixed_arm_skeleton_dialog is None
    finally:
        monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)
        if window.isVisible():
            window.close()


def test_fixed_editor_stays_alive_if_worker_does_not_stop_then_closes_on_retry(qtbot, monkeypatch):
    import threading

    from suspensionlab.core.cad_transport import CadPreviewError
    from suspensionlab.ui import weldment_3d
    from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog

    started, release = threading.Event(), threading.Event()
    class UnresponsiveJob:
        def __init__(self):
            self.cancelled = False
        def cancel(self):
            self.cancelled = True
        def run(self, _document, *, deviation=2.):
            started.set()
            release.wait(15)
            raise CadPreviewError('cancelled')

    monkeypatch.setattr(weldment_3d, 'WeldmentCadJob', UnresponsiveJob)
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._capture_snapshot()
    worker = _start_cad(dialog._cad)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        assert not dialog.close()
        assert dialog.isVisible() and dialog._cad._closed and worker.isRunning() and worker.job.cancelled
        release.set()
        qtbot.waitUntil(lambda: dialog._cad._worker is None, timeout=5000)
        assert dialog.close()
    finally:
        release.set()
        dialog.shutdown()
        dialog.close()


def test_escape_refusal_preserves_real_cad_then_confirmation_closes(qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import Qt

    controller = AppController()
    controller.project = load_template('ring')
    window = MainWindow(controller, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()
    window._open_fixed_arm_skeleton()
    dialog = window._fixed_arm_skeleton_dialog
    dialog._capture_snapshot()
    panel = dialog._cad
    worker = _start_cad(panel)
    qtbot.waitUntil(lambda: _process_of(worker) is not None, timeout=30000)
    process = _process_of(worker)
    assert process is not None
    answers = []
    def choose(*_args):
        answers.append('asked')
        return QMessageBox.StandardButton.No if len(answers) == 1 else QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', choose)
    try:
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.isVisible() and not panel._closed and not worker.job._job.is_cancelled()
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
        assert answers == ['asked', 'asked'] and not dialog.isVisible()
        assert window._fixed_arm_skeleton_dialog is None and panel._closed and not worker.isRunning()
        assert process.poll() is not None
    finally:
        monkeypatch.setattr(QMessageBox, 'question', lambda *_args: QMessageBox.StandardButton.Yes)
        if window.isVisible():
            window.close()
