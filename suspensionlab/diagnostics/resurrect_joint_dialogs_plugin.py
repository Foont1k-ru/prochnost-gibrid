"""Isolated experimental handoff of unreachable JointConceptDialog wrappers.

Not an application fix: `__del__` resurrection, gc.collect in a Qt slot and
interpreter/application shutdown have unresolved semantics and may crash or
block the GUI. Run only in a disposable pytest process with -s; never enable in
production. Existing tests must not be relaxed.
"""
from __future__ import annotations

import gc
import threading

from PySide6.QtCore import QObject, Qt, Signal, Slot

from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

_main = threading.get_ident()
_original_init = JointConceptDialog.__init__
_held: list[JointConceptDialog] = []
_dispatcher = None
_handoffs = 0
_drains = 0
_foreign_destroyed = 0


class _Dispatcher(QObject):
    release = Signal()

    def __init__(self):
        super().__init__()
        self.release.connect(self.drain, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def drain(self):
        global _drains
        _drains += 1
        _held.clear()
        gc.collect()


def _init(dialog, *args, **kwargs):
    global _dispatcher
    _original_init(dialog, *args, **kwargs)
    if _dispatcher is None:
        _dispatcher = _Dispatcher()

    def destroyed(*_args):
        global _foreign_destroyed
        _foreign_destroyed += int(threading.get_ident() != _main)

    dialog.destroyed.connect(destroyed, Qt.ConnectionType.DirectConnection)


def _finalize(dialog):
    global _handoffs
    if threading.get_ident() != _main and _dispatcher is not None:
        _handoffs += 1
        _held.append(dialog)
        _dispatcher.release.emit()


def pytest_configure(config):
    JointConceptDialog.__init__ = _init
    JointConceptDialog.__del__ = _finalize


def pytest_sessionfinish(session, exitstatus):
    print(f'RESURRECTION handoffs={_handoffs} drains={_drains} retained={len(_held)} '
          f'foreign-destroyed={_foreign_destroyed}', flush=True)


def pytest_unconfigure(config):
    JointConceptDialog.__init__ = _original_init
    del JointConceptDialog.__del__
