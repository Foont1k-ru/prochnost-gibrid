"""Isolated, intentionally unsafe GC experiment; never enable in the application.

An unreachable parentless dialog is resurrected once on a worker, then retained
and shown again, released, and collected on a worker a second time. This probes
weakrefs and repeat finalization, not a fix or proof of the original crash.
Each trial runs in a separate child with core dumps disabled.
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import threading
import weakref


def child() -> int:
    if os.name == 'posix':
        import resource
        _, hard = resource.getrlimit(resource.RLIMIT_CORE)
        resource.setrlimit(resource.RLIMIT_CORE, (0, hard))
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid

    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

    app = QApplication([])
    gui_thread = threading.get_ident()
    retained = []
    finalizers = []
    destroyed = []

    class ExperimentDialog(JointConceptDialog):
        def __del__(self):
            finalizers.append(threading.get_ident() == gui_thread)
            retained.append(self)

    gc.disable()
    dialog = ExperimentDialog(AppController())
    dialog.destroyed.connect(lambda *_: destroyed.append(threading.get_ident() == gui_thread),
                             Qt.ConnectionType.DirectConnection)
    reference = weakref.ref(dialog)
    dialog.show()
    dialog.close()
    del dialog
    collector = threading.Thread(target=gc.collect)
    collector.start()
    collector.join()
    first = {'handoffs': len(retained), 'finalizer_on_gui': finalizers[:], 'weakref_alive': reference() is not None,
             'destroyed': destroyed[:]}
    print('REUSE_FIRST ' + json.dumps(first), flush=True)
    if len(retained) != 1:
        return 2
    # A strong owner can still reuse the resurrected wrapper; its original weakref
    # may already be dead. No queued signal, event-loop shutdown or production
    # ownership strategy is implied by this artificial adoption.
    dialog = retained.pop()
    if not isValid(dialog):
        return 3
    dialog.show()
    reused = dialog.isVisible()
    dialog.close()
    del dialog
    collector = threading.Thread(target=gc.collect)
    collector.start()
    collector.join()
    second = {'reused': reused, 'handoffs': len(retained), 'finalizer_on_gui': finalizers[:],
              'weakref_alive': reference() is not None, 'destroyed_on_gui': destroyed[:]}
    print('REUSE_SECOND ' + json.dumps(second), flush=True)
    # Drain any Qt events only after recording the worker-side outcome.
    app.processEvents()
    gc.enable()
    return 0


def main() -> int:
    if '--child' in sys.argv:
        return child()
    failures = 0
    for trial in range(3):
        result = subprocess.run([sys.executable, '-u', __file__, '--child'],
                                env={**os.environ, 'PYTHONFAULTHANDLER': '1'}, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=60, check=False)
        print(f'TRIAL {trial + 1}: exit={result.returncode}', flush=True)
        print(result.stdout[-5000:], flush=True)
        if result.returncode:
            failures += 1
            print(result.stderr[-5000:], flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
