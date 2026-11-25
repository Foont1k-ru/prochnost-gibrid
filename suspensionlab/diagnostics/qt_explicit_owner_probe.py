"""Isolated explicit-owner experiment with real CAD; not an application fix.

A hidden QWidget explicitly owns two JointConceptDialog instances. The first is
hidden and shown while alive, then closed while its CAD process is running; a
fresh instance is opened after that terminal close. A foreign GC runs while the
owner remains alive, and the owner is finally deleted on the GUI thread. Run
only as a standalone subprocess experiment, not inside the product or pytest.
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import threading
import time
import weakref


def child() -> int:
    if os.name == 'posix':
        import resource
        _, hard = resource.getrlimit(resource.RLIMIT_CORE)
        resource.setrlimit(resource.RLIMIT_CORE, (0, hard))
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from shiboken6 import isValid

    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    gui_thread = threading.get_ident()
    gc.disable()
    owner = QWidget()
    controller = AppController()
    destructions: list[tuple[int, bool]] = []
    references = []

    def wait_until(condition, timeout=45):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() >= deadline:
                raise TimeoutError('condition not reached')
            app.processEvents()
            time.sleep(0.01)

    def worker_gc():
        collector = threading.Thread(target=gc.collect)
        collector.start()
        collector.join()

    def make_dialog(number):
        dialog = JointConceptDialog(controller, owner)
        dialog.destroyed.connect(lambda *_: destructions.append((number, threading.get_ident() == gui_thread)),
                                 Qt.ConnectionType.DirectConnection)
        references.append(weakref.ref(dialog))
        dialog.show()
        return dialog

    def begin_real_cad(dialog):
        panel = dialog._three_d
        panel._enable.setChecked(True)
        panel._timer.stop()
        panel._start()

        def process_running():
            worker = panel._worker
            if worker is None:
                return False
            job = worker.job._job
            with job._lock:
                return job._process is not None and job._process.poll() is None

        wait_until(process_running, timeout=20)
        return panel._worker

    first = make_dialog(1)
    begin_real_cad(first)
    first.hide()
    first.show()
    assert first.isVisible() and not first._three_d._closed
    wait_until(lambda dialog=first: dialog._three_d._ready and dialog._three_d._worker is None)
    assert first._three_d._view.mesh is not None
    first._fields['ball']['outer_radius_mm'].setText('23')
    first.confirm_close = lambda: True  # Avoid a modal prompt; lifecycle experiment only.
    worker = begin_real_cad(first)
    worker_gc()
    assert first.close() and first._three_d._closed and not worker.isRunning()
    del worker, first
    worker_gc()
    assert references[0]() is not None and isValid(references[0]()) and not destructions
    print('OWNER first_closed_retained=true worker_stopped=true hidden_then_shown=true', flush=True)

    second = make_dialog(2)  # A closed CAD panel is terminal: reopen as a new dialog.
    assert second._fields['ball']['outer_radius_mm'].text() != '23'
    worker = begin_real_cad(second)
    worker_gc()
    assert second.close() and second._three_d._closed and not worker.isRunning()
    del worker, second
    worker_gc()
    assert all(reference() is not None and isValid(reference()) for reference in references) and not destructions
    print('OWNER second_closed_retained=true worker_stopped=true foreign_gc_safe_so_far=true', flush=True)

    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert sorted(destructions) == [(1, True), (2, True)]
    assert all(reference() is None or not isValid(reference()) for reference in references)
    print('OWNER_RESULT ' + json.dumps({'destroyed': destructions, 'all_on_gui': True,
                                        'wrappers_invalid_or_gone': True}), flush=True)
    gc.enable()
    return 0


def main() -> int:
    if '--child' in sys.argv:
        return child()
    failures = 0
    for trial in range(3):
        result = subprocess.run([sys.executable, '-u', __file__, '--child'],
                                env={**os.environ, 'PYTHONFAULTHANDLER': '1'}, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=120, check=False)
        print(f'TRIAL {trial + 1}: exit={result.returncode}', flush=True)
        print(result.stdout[-5000:], flush=True)
        if result.returncode:
            failures += 1
            print(result.stderr[-5000:], flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
