"""Diagnostic-only test-scoped owner; NOT a fix for the application or pytest.

Attach a hidden QWidget owner only to otherwise parentless JointConceptDialog
instances. After the original pytest teardown (including qtbot), stop their CAD,
then delete their owners in the GUI thread. This changes ownership and timing;
never use its results as an uninstrumented or full regression run.
"""
from __future__ import annotations

import gc
import threading

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget

from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

_main = threading.get_ident()
_original_init = JointConceptDialog.__init__
_owners: list[QWidget] = []
_stranded: list[QWidget] = []
_created = _destroyed = _foreign_destroyed = _foreign_gc = 0


def _init(dialog, controller, parent=None):
    global _created
    if parent is None:
        parent = QWidget()
        _owners.append(parent)
        _created += 1
        def destroyed(*_args):
            global _destroyed, _foreign_destroyed
            _destroyed += 1
            _foreign_destroyed += int(threading.get_ident() != _main)
        _original_init(dialog, controller, parent)
        dialog.destroyed.connect(destroyed, Qt.ConnectionType.DirectConnection)
    else:
        _original_init(dialog, controller, parent)


def _gc_watch(phase, _info):
    global _foreign_gc
    if phase == 'start' and threading.get_ident() != _main:
        _foreign_gc += 1


def pytest_configure(config):
    JointConceptDialog.__init__ = _init
    gc.callbacks.append(_gc_watch)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    yield
    owners, _owners[:] = _owners[:], []
    if not owners:
        return
    assert threading.get_ident() == _main
    # Qtbot teardown has already run. Do not destroy a window with a running worker.
    for owner in owners:
        for dialog in owner.findChildren(JointConceptDialog):
            if not dialog.shutdown():
                _stranded.append(owner)
                raise RuntimeError('diagnostic owner retained: CAD worker did not stop')
        owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def pytest_sessionfinish(session, exitstatus):
    print(f'EXPLICIT_OWNER created={_created} destroyed={_destroyed} '
          f'foreign-destroyed={_foreign_destroyed} foreign-gc={_foreign_gc} '
          f'pending={len(_owners)} stranded={len(_stranded)}', flush=True)


def pytest_unconfigure(config):
    JointConceptDialog.__init__ = _original_init
    if _gc_watch in gc.callbacks:
        gc.callbacks.remove(_gc_watch)
