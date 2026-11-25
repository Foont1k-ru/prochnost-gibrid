"""Opt-in native-debugging aid: map Python-created form labels to C++ addresses.

For isolated local pytest runs only. Addresses and test identifiers are diagnostic
information: never write logs to the repository. Wrapping and printing change timing.
Only addRow(str, QWidget) calls made through Python are observed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QFormLayout, QLabel, QWidget
from shiboken6 import getCppPointer

_original_add_row = QFormLayout.addRow
_current_test = '<collection>'


def _add_row(form, *args):
    result = _original_add_row(form, *args)
    if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], QWidget):
        label = form.labelForField(args[1])
        if isinstance(label, QLabel):
            address = getCppPointer(label)[0]
            source = Path(sys._getframe(1).f_code.co_filename).name
            print(f'FORM_ADDRESS label={address:#x} source={source} field={type(args[1]).__name__} '
                  f'test={_current_test}', flush=True)
    return result


def pytest_configure(config):
    QFormLayout.addRow = _add_row


def pytest_runtest_setup(item):
    global _current_test
    _current_test = item.nodeid


def pytest_unconfigure(config):
    QFormLayout.addRow = _original_add_row
