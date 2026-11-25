"""Experimental, isolated-only lifecycle probe; NOT an application fix.

Tests whether a Python finalizer can temporarily resurrect parentless dialogs and
transfer final collection to the Qt thread. This can crash and has unresolved
interpreter-shutdown, weakref and ownership semantics. Runs child processes with
core dumps disabled; never import or enable this in the product.
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import threading


def child() -> int:
    if os.name == 'posix':
        import resource
        _, hard = resource.getrlimit(resource.RLIMIT_CORE)
        resource.setrlimit(resource.RLIMIT_CORE, (0, hard))
    from PySide6.QtCore import QObject, Qt, Signal, Slot
    from PySide6.QtWidgets import QApplication

    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

    app = QApplication([])
    main_thread = threading.get_ident()
    held = []
    finalizers = []
    destroyed = []

    class Dispatcher(QObject):
        release = Signal()

        def __init__(self):
            super().__init__()
            self.release.connect(self.drain, Qt.ConnectionType.QueuedConnection)

        @Slot()
        def drain(self):
            held.clear()
            gc.collect()

    dispatcher = Dispatcher()

    class ExperimentDialog(JointConceptDialog):
        def __del__(self):
            foreign = threading.get_ident() != main_thread
            finalizers.append(foreign)
            if foreign:
                held.append(self)
                dispatcher.release.emit()

    gc.disable()
    controller = AppController()
    dialogs = []
    for index in range(5):
        dialog = ExperimentDialog(controller)
        dialog.destroyed.connect(lambda *_args, index=index: destroyed.append((index, threading.get_ident())),
                                 Qt.ConnectionType.DirectConnection)
        dialog.show()
        dialog.close()
        dialog.show()  # Ordinary externally retained dialog can still be shown again.
        assert dialog.isVisible()
        dialog.close()
        dialogs.append(dialog)
    del dialog
    gc.collect()
    assert not destroyed  # Externally retained objects must not be deleted.
    dialogs.clear()
    collector = threading.Thread(target=gc.collect)
    collector.start()
    collector.join()
    before = {'finalizers': finalizers[:], 'destroyed': destroyed[:], 'held': len(held)}
    app.processEvents()
    gc.collect()
    after = {'finalizers': finalizers[:], 'destroyed_threads': [thread == main_thread for _, thread in destroyed],
             'destroyed_count': len(destroyed), 'held': len(held)}
    print('RESURRECTION_PROBE ' + json.dumps({'before': before, 'after': after}), flush=True)
    gc.enable()
    return 0 if len(destroyed) == 5 and all(thread == main_thread for _, thread in destroyed) else 1


def main() -> int:
    if '--child' in sys.argv:
        return child()
    result = subprocess.run([sys.executable, '-u', __file__, '--child'],
                            env={**os.environ, 'PYTHONFAULTHANDLER': '1'}, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=60, check=False)
    print('exit:', result.returncode)
    print(result.stdout[-5000:])
    if result.returncode:
        print(result.stderr[-5000:])
    return 0 if result.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
