"""Регрессии совместимости PySide: код выхода процесса важнее результатов утверждений."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement


def _run_child(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        env=env, capture_output=True, text=True, timeout=90, check=False,
    )


def test_pyside_dependency_is_selected_for_each_supported_python():
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [Requirement(s) for s in project["project"]["dependencies"]]
    qt = [r for r in requirements if r.name.lower() == "pyside6-essentials"]
    for version, expected in (("3.11", "==6.11.3"), ("3.12", "==6.11.3"), ("3.13", "==6.12.0")):
        env = default_environment() | {"python_version": version}
        selected = [str(r.specifier) for r in qt if r.marker is None or r.marker.evaluate(env)]
        assert selected == [expected]


def test_qt_void_calls_and_boolean_signals_do_not_corrupt_singletons():
    result = _run_child('''
        import gc
        import platform
        import sys
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QApplication, QLabel, QTableWidget, QTableWidgetItem
        app = QApplication([])
        table = QTableWidget(1, 1)
        label = QLabel()
        class Emitter(QObject):
            changed = Signal(bool)
        emitter = Emitter()
        received = []
        emitter.changed.connect(received.append)
        def run():
            for i in range(1000):
                label.setText('text')
                table.setItem(0, 0, QTableWidgetItem('value'))
                emitter.changed.emit(bool(i % 2))
            received.clear()
        run()
        gc.collect()
        before = tuple(sys.getrefcount(value) for value in (None, True, False))
        run()
        gc.collect()
        after = tuple(sys.getrefcount(value) for value in (None, True, False))
        print('before', before, 'after', after, flush=True)
        if platform.python_implementation() == 'CPython' and sys.version_info < (3, 12):
            assert all(a >= b - 20 for a, b in zip(after, before)), (before, after)
    ''')
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_repeated_point_table_lifecycle_exits_cleanly():
    result = _run_child('''
        import gc
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        from suspensionlab.ui.controller import AppController
        from suspensionlab.ui.point_table_dialog import PointTableDialog
        app = QApplication([])
        controller = AppController()
        for _ in range(25):
            dialog = PointTableDialog(controller)
            dialog.show()
            app.processEvents()
            dialog.close()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            del dialog
            gc.collect()
        print('25 dialogs closed', flush=True)
    ''')
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
