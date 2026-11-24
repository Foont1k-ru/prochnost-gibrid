"""Opt-in pytest tracer for QFormLayout label/buddy lifetimes; not a fix.

Run isolated with ``PYTHONPATH=diagnostics python -m pytest -s -p
trace_form_buddies_plugin ...``. Records only rows added through Python with a
string label and QWidget field. Connections, tracing and disabled pytest Qt-log
capture with -s alter timing. No document data or widget text is recorded.
"""
from __future__ import annotations

import gc
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

_main_thread = threading.get_ident()
_original_add_row = QFormLayout.addRow
_current_test = '<collection>'
_pairs = 0
_foreign_destroyed = 0
_foreign_gc = 0


def _add_row(form, *args):
    global _pairs
    result = _original_add_row(form, *args)
    if len(args) != 2 or not isinstance(args[0], str) or not isinstance(args[1], QWidget):
        return result
    field = args[1]
    label = form.labelForField(field)
    if not isinstance(label, QLabel) or label.buddy() is not field:
        return result
    _pairs += 1
    pair = _pairs
    created_in = _current_test
    field_type = type(field).__name__
    for widget, role in ((label, 'label'), (field, 'field')):
        def destroyed(*_args, role=role, pair=pair, created_in=created_in, field_type=field_type):
            global _foreign_destroyed
            if threading.get_ident() != _main_thread:
                _foreign_destroyed += 1
                print(f'TRACE foreign-{role} pair={pair} field={field_type} created-in={created_in}', flush=True)

        widget.destroyed.connect(destroyed, Qt.ConnectionType.DirectConnection)
    return result


def _gc_watch(phase, info):
    global _foreign_gc
    if phase == 'start' and threading.get_ident() != _main_thread:
        _foreign_gc += 1
        if _foreign_gc <= 20:
            print(f'TRACE foreign-gc generation={info["generation"]} active-test={_current_test}', flush=True)


def pytest_configure(config):
    QFormLayout.addRow = _add_row
    gc.callbacks.append(_gc_watch)


def pytest_runtest_setup(item):
    global _current_test
    _current_test = item.nodeid


def pytest_sessionfinish(session, exitstatus):
    print(f'TRACE pairs={_pairs} foreign-gc={_foreign_gc} foreign-destructions={_foreign_destroyed}', flush=True)


def pytest_unconfigure(config):
    QFormLayout.addRow = _original_add_row
    if _gc_watch in gc.callbacks:
        gc.callbacks.remove(_gc_watch)
