"""Optional dialog-lifetime tracer; changes timing and does not fix Qt.

Run only in an isolated process with PYTHONPATH=diagnostics pytest -s -p
trace_joint_lifecycle_plugin <tests>. Records identity and thread, not widget
contents. The DirectConnection and weakref callbacks alter object lifetimes.
"""
from __future__ import annotations

import gc
import threading
import weakref

from PySide6.QtCore import Qt
from shiboken6 import getCppPointer

from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

_main = threading.get_ident()
_original_init = JointConceptDialog.__init__
_current_test = '<collection>'
_weakrefs: list[weakref.ReferenceType] = []
_created = _foreign_destroyed = _foreign_finalized = _foreign_gc = 0


def _init(dialog, *args, **kwargs):
    global _created
    _original_init(dialog, *args, **kwargs)
    _created += 1
    serial, address, parentless, created = _created, getCppPointer(dialog)[0], dialog.parent() is None, _current_test
    print(f'JOINT create n={serial} cpp={address:#x} parentless={parentless} test={created}', flush=True)

    def on_destroyed(*_args):
        global _foreign_destroyed
        foreign = threading.get_ident() != _main
        _foreign_destroyed += int(foreign)
        print(f'JOINT destroy n={serial} foreign={foreign} test={_current_test}', flush=True)

    def on_wrapper_collected(_reference):
        global _foreign_finalized
        foreign = threading.get_ident() != _main
        _foreign_finalized += int(foreign)
        print(f'JOINT wrapper-finalized n={serial} foreign={foreign} test={_current_test}', flush=True)

    dialog.destroyed.connect(on_destroyed, Qt.ConnectionType.DirectConnection)
    _weakrefs.append(weakref.ref(dialog, on_wrapper_collected))


def _gc_watch(phase, info):
    global _foreign_gc
    if phase == 'start' and threading.get_ident() != _main:
        _foreign_gc += 1
        print(f'JOINT foreign-gc generation={info["generation"]} test={_current_test}', flush=True)


def pytest_configure(config):
    JointConceptDialog.__init__ = _init
    gc.callbacks.append(_gc_watch)


def pytest_runtest_setup(item):
    global _current_test
    _current_test = item.nodeid


def pytest_sessionfinish(session, exitstatus):
    print(f'JOINT summary created={_created} foreign-destroyed={_foreign_destroyed} '
          f'foreign-wrapper-finalized={_foreign_finalized} foreign-gc={_foreign_gc}', flush=True)


def pytest_unconfigure(config):
    JointConceptDialog.__init__ = _original_init
    if _gc_watch in gc.callbacks:
        gc.callbacks.remove(_gc_watch)
