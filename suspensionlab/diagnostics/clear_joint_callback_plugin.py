"""Diagnostic-only callback-cycle experiment; not an application fix.

After a successful JointConceptDialog.shutdown, release the CAD panel's bound
current-document callback. This changes object lifetime and timing. Use only
in isolated pytest processes and compare with an unmodified control.
"""
from __future__ import annotations

from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

_original_shutdown = JointConceptDialog.shutdown
_cleared = 0


def _shutdown(dialog):
    global _cleared
    stopped = _original_shutdown(dialog)
    if stopped and dialog._three_d._is_current is not None:
        dialog._three_d._is_current = None
        _cleared += 1
    return stopped


def pytest_configure(config):
    JointConceptDialog.shutdown = _shutdown


def pytest_sessionfinish(session, exitstatus):
    print(f'CALLBACK_DIAGNOSTIC cleared={_cleared}', flush=True)


def pytest_unconfigure(config):
    JointConceptDialog.shutdown = _original_shutdown
