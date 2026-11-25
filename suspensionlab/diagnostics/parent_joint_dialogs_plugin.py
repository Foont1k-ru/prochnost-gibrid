"""Diagnostic-only parent ownership for otherwise parentless joint dialogs.

Not an application change or a test-suite fix. A hidden Qt owner is kept alive for
this isolated pytest process. It changes window lifecycle and can hide defects;
compare the unmodified scenario and never count it as a full regression pass.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

_original_init = JointConceptDialog.__init__
_owners: list[QWidget] = []


def _init(self, controller, parent=None):
    if parent is None:
        parent = QWidget()
        _owners.append(parent)
    _original_init(self, controller, parent)


def pytest_configure(config):
    JointConceptDialog.__init__ = _init


def pytest_sessionfinish(session, exitstatus):
    print(f'DIAGNOSTIC parented_joint_dialogs={len(_owners)}', flush=True)


def pytest_unconfigure(config):
    JointConceptDialog.__init__ = _original_init
