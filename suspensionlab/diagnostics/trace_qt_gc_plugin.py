"""Необязательный pytest-плагин: наблюдение GC и закрытых диалогов, не защита Qt.

Пример из suspensionlab: PYTHONPATH=diagnostics python -m pytest -s -p trace_qt_gc_plugin
Наблюдение ограничено: диалог подключается только в конце тестового вызова,
поэтому не отслеживаются окна, уничтоженные раньше или не попавшие в список Qt.
"""
from __future__ import annotations

import gc
import threading
import weakref

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

_main_thread = threading.get_ident()
_seen: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_foreign_gc = 0
_foreign_deletes = 0


def _gc_watch(phase, info):
    global _foreign_gc
    if phase == 'start' and threading.get_ident() != _main_thread:
        _foreign_gc += 1
        if _foreign_gc <= 10:
            print(f'TRACE foreign-gc generation={info["generation"]}', flush=True)


gc.callbacks.append(_gc_watch)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    yield
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        if not isinstance(widget, QDialog) or widget in _seen:
            continue
        _seen[widget] = True
        name = type(widget).__module__ + '.' + type(widget).__name__

        def destroyed(*_args, name=name, test=item.nodeid):
            global _foreign_deletes
            if threading.get_ident() != _main_thread:
                _foreign_deletes += 1
                print(f'TRACE foreign-dialog-destruction class={name} tracked-after-test={test}', flush=True)

        widget.destroyed.connect(destroyed, Qt.ConnectionType.DirectConnection)


def pytest_sessionfinish(session, exitstatus):
    print(f'TRACE total_foreign_gc={_foreign_gc} total_foreign_dialog_destruction={_foreign_deletes}', flush=True)


def pytest_unconfigure(config):
    if _gc_watch in gc.callbacks:
        gc.callbacks.remove(_gc_watch)
