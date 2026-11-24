"""Необязательное узкое наблюдение QLabel и buddy редактора шарнира в pytest.

Пример из suspensionlab: PYTHONPATH=diagnostics python -m pytest -s -p trace_joint_buddies_plugin
Подключение к сигналам и вывод меняют время выполнения. Наблюдаются только метки
с buddy, существующие после конструктора JointConceptDialog; оно не устанавливает
причину аварии и не защищает от неё. Снимки состояний и данные проекта не пишутся.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

_main_thread = threading.get_ident()
_original_init = JointConceptDialog.__init__
_current_test = '<collection>'
_dialog_count = 0
_pair_count = 0
_foreign_events = 0


def _observed_init(self, *args, **kwargs):
    global _dialog_count, _pair_count
    _original_init(self, *args, **kwargs)
    _dialog_count += 1
    dialog_number = _dialog_count
    test = _current_test
    pairs_before = _pair_count
    for label in self.findChildren(QLabel):
        buddy = label.buddy()
        if buddy is None:
            continue
        _pair_count += 1
        pair_number = _pair_count
        for widget, role in ((label, 'label'), (buddy, 'buddy')):
            def destroyed(*_args, role=role, pair_number=pair_number, dialog_number=dialog_number, test=test):
                global _foreign_events
                if threading.get_ident() != _main_thread:
                    _foreign_events += 1
                    print(f'TRACE foreign-{role}-destruction dialog={dialog_number} pair={pair_number} '
                          f'created-in={test}', flush=True)

            widget.destroyed.connect(destroyed, Qt.ConnectionType.DirectConnection)
    print(f'TRACE joint-dialog={dialog_number} label-buddy-pairs={_pair_count - pairs_before} '
          f'created-in={test}', flush=True)


def pytest_configure(config):
    JointConceptDialog.__init__ = _observed_init


def pytest_runtest_setup(item):
    global _current_test
    _current_test = item.nodeid


def pytest_sessionfinish(session, exitstatus):
    print(f'TRACE joint-dialogs={_dialog_count} label-buddy-pairs={_pair_count} '
          f'foreign-widget-destructions={_foreign_events}', flush=True)


def pytest_unconfigure(config):
    JointConceptDialog.__init__ = _original_init
