"""Diagnostic-only pytest intervention: detach automatically created form buddies.

This changes Qt accessibility/mnemonic behaviour and MUST NOT be used in the app
or accepted as a correctness run or fix. It is used only in isolated subprocesses
to probe a suspected Qt lifecycle mechanism and is not comprehensive.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

_original_add_row = QFormLayout.addRow
_count = 0
_scope = os.environ.get('QT_DIAG_BUDDY_SCOPE', 'all')
if _scope not in ('all', 'joint', 'other'):
    raise ValueError('QT_DIAG_BUDDY_SCOPE must be all, joint or other')


def _add_row(form, *args):
    global _count
    result = _original_add_row(form, *args)
    caller_is_joint = Path(sys._getframe(1).f_code.co_filename).name == 'joint_concept_dialog.py'
    in_scope = _scope == 'all' or (_scope == 'joint' and caller_is_joint) or (_scope == 'other' and not caller_is_joint)
    if in_scope and len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], QWidget):
        label = form.labelForField(args[1])
        if isinstance(label, QLabel) and label.buddy() is args[1]:
            label.setBuddy(None)
            _count += 1
    return result


def pytest_configure(config):
    QFormLayout.addRow = _add_row


def pytest_sessionfinish(session, exitstatus):
    print(f'DIAGNOSTIC scope={_scope} disabled_form_buddies={_count}', flush=True)


def pytest_unconfigure(config):
    QFormLayout.addRow = _original_add_row
