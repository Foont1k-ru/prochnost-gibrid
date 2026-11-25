"""Isolated explicit-owner and event-loop exit experiment; not an application fix.

Run a real CAD subprocess under a hidden QWidget owner, simulate one failed
worker wait, retain the live owner, then retry close after the worker stops.
The coordinator deletes the owner on the GUI thread before asking QApplication
to quit. A strong external Python reference is deliberately kept after Qt
object deletion. Each trial is a disposable child with core dumps disabled.
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import threading
import time


def child() -> int:
    if os.name == 'posix':
        import resource
        _, hard = resource.getrlimit(resource.RLIMIT_CORE)
        resource.setrlimit(resource.RLIMIT_CORE, (0, hard))
    from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    from shiboken6 import isValid

    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    main_thread = threading.get_ident()
    owner = QWidget()
    dialog = JointConceptDialog(AppController(), owner)
    panel = dialog._three_d
    events: list[tuple[str, bool]] = []
    dialog.destroyed.connect(lambda *_: events.append(('dialog', threading.get_ident() == main_thread)),
                             Qt.ConnectionType.DirectConnection)
    owner.destroyed.connect(lambda *_: events.append(('owner', threading.get_ident() == main_thread)),
                            Qt.ConnectionType.DirectConnection)
    quit_state = []
    app.aboutToQuit.connect(lambda: quit_state.append((threading.get_ident() == main_thread,
                                                       not isValid(dialog), not isValid(owner))))
    dialog.show()
    panel._enable.setChecked(True)
    panel._timer.stop()
    panel._start()
    state = {'phase': 'running', 'timeout_observed': False, 'stopped': False, 'quit_requested': False}
    errors = []
    deadline = time.monotonic() + 45
    timer = QTimer()
    timer.setInterval(10)

    def tick():
        try:
            if time.monotonic() > deadline:
                raise TimeoutError('event-loop experiment timed out')
            if state['phase'] == 'running':
                worker = panel._worker
                if worker is None:
                    return
                job = worker.job._job
                with job._lock:
                    running = job._process is not None and job._process.poll() is None
                if not running:
                    return
                original_wait = worker.wait
                worker.wait = lambda *_args: False  # Simulated timeout, real subprocess/worker.
                try:
                    assert not dialog.close()
                finally:
                    worker.wait = original_wait
                assert isValid(owner) and isValid(dialog) and dialog.isVisible() and panel._closed
                assert not panel.can_save() and panel._view.mesh is None and not events
                thread = threading.Thread(target=gc.collect)
                thread.start()
                thread.join()
                assert isValid(owner) and isValid(dialog) and not events
                state.update(phase='wait-for-worker', timeout_observed=True)
            elif state['phase'] == 'wait-for-worker':
                if panel._worker is not None:
                    return
                assert dialog.close()
                state.update(phase='deleting', stopped=True)
                owner.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                assert sorted(events) == [('dialog', True), ('owner', True)]
                assert not isValid(owner) and not isValid(dialog)
                state['quit_requested'] = True
                timer.stop()
                app.quit()
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
            timer.stop()
            # Do not pretend forced termination is safe. Child process exit is
            # isolated and failures are reported by the controlling process.
            app.exit(2)

    timer.timeout.connect(tick)
    timer.start()
    exit_code = app.exec()
    result = {'state': state, 'events': events, 'about_to_quit': quit_state,
              'event_loop_exit': exit_code, 'errors': errors}
    print('OWNER_EXIT_RESULT ' + json.dumps(result), flush=True)
    return 0 if (exit_code == 0 and state['quit_requested'] and quit_state == [(True, True, True)] and not errors) else 1


def main() -> int:
    if '--child' in sys.argv:
        return child()
    failures = 0
    for trial in range(3):
        result = subprocess.run([sys.executable, '-u', __file__, '--child'],
                                env={**os.environ, 'PYTHONFAULTHANDLER': '1'}, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=90, check=False)
        print(f'TRIAL {trial + 1}: exit={result.returncode}', flush=True)
        print(result.stdout[-5000:], flush=True)
        if result.returncode:
            failures += 1
            print(result.stderr[-5000:], flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
