"""Isolated callback-cycle observation, not an application fix.

Compare a normal closed parentless joint dialog with one whose *already closed*
CAD panel's document-current callback is cleared. GC is disabled, then forced on
a worker; destruction thread and weakref state are recorded before GUI events.
Each run is a subprocess because either variant may crash. No tests are changed.
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import threading
import weakref


def child(clear: bool) -> int:
    if os.name == 'posix':
        import resource
        _, hard = resource.getrlimit(resource.RLIMIT_CORE)
        resource.setrlimit(resource.RLIMIT_CORE, (0, hard))
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

    app = QApplication([])
    main_thread = threading.get_ident()
    destruction = []
    gc.disable()
    dialog = JointConceptDialog(AppController())
    dialog.destroyed.connect(lambda *_: destruction.append(threading.get_ident() == main_thread),
                             Qt.ConnectionType.DirectConnection)
    reference = weakref.ref(dialog)
    dialog.show()
    assert dialog.close() and dialog._three_d._closed
    if clear:
        dialog._three_d._is_current = None
    del dialog
    before = {'weakref_alive': reference() is not None, 'destroyed_on_gui': destruction[:]}
    collector = threading.Thread(target=gc.collect)
    collector.start()
    collector.join()
    after = {'weakref_alive': reference() is not None, 'destroyed_on_gui': destruction[:]}
    print('CYCLE_RESULT ' + json.dumps({'clear': clear, 'before_worker_gc': before, 'after_worker_gc': after}),
          flush=True)
    app.processEvents()
    gc.enable()
    return 0


def main() -> int:
    if '--child' in sys.argv:
        return child(sys.argv[2] == 'clear')
    failures = 0
    for trial in range(3):
        for mode in ('control', 'clear'):
            result = subprocess.run([sys.executable, '-u', __file__, '--child', mode],
                                    env={**os.environ, 'PYTHONFAULTHANDLER': '1'}, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=60, check=False)
            print(f'TRIAL {trial + 1} {mode}: exit={result.returncode}', flush=True)
            print(result.stdout[-3000:], flush=True)
            if result.returncode:
                failures += 1
                print(result.stderr[-3000:], flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
