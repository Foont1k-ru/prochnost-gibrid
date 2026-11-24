"""Reproduce programmatic close while a joint file prompt returns.

Runs each case in a child process with core dumps disabled. File dialogs are
replaced by callbacks which close the parent and return a selected test path;
this is an adversarial reentrancy simulation, not a native dialog test. A
nonzero exit reports an exception, a post-close warning, or a mutation/write.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def child(kind: str, flush: bool) -> int:
    if os.name == 'posix':
        import resource
        _, hard = resource.getrlimit(resource.RLIMIT_CORE)
        resource.setrlimit(resource.RLIMIT_CORE, (0, hard))
    from PySide6.QtCore import QCoreApplication, QEvent, QSettings
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from shiboken6 import isValid

    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept
    from suspensionlab.model.kim_format import write_document
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.main_window import MainWindow

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix='suspension-modal-probe-') as directory:
        root = Path(directory)
        source, target = root / 'source.kima', root / 'copy.kima'
        write_document(source, 'assembly', make_joint_concept('bushing', DEFAULTS['bushing']))
        window = MainWindow(AppController(), QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat))
        window.show()
        window._open_joint_concept()
        dialog = window._joint_concept_dialog
        assert dialog is not None
        before = dialog._candidate
        warnings = []

        def selected(*_args):
            assert dialog.close()
            if flush:
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            return str(source if kind == 'open' else target), ''

        error = None
        name = 'getOpenFileName' if kind == 'open' else 'getSaveFileName'
        with patch.object(QFileDialog, name, side_effect=selected), \
                patch.object(QMessageBox, 'warning', side_effect=lambda *_args: warnings.append(True)):
            try:
                (dialog._open_file if kind == 'open' else dialog._save_copy)()
            except Exception as exc:  # report without trying to access a deleted Qt object
                error = type(exc).__name__
        alive = isValid(dialog)
        changed = alive and dialog._candidate != before
        result = {'kind': kind, 'flush': flush, 'valid': alive, 'exception': error,
                  'changed': bool(changed), 'warnings': len(warnings), 'written': target.exists()}
        print('MODAL_RESULT ' + json.dumps(result), flush=True)
        window.close()
        return int(bool(error or changed or warnings or target.exists()))


def main() -> int:
    if '--child' in sys.argv:
        return child(sys.argv[2], sys.argv[3] == 'flush')
    failed = 0
    for kind in ('open', 'save'):
        for flush in ('pending', 'flush'):
            process = subprocess.run([sys.executable, '-u', __file__, '--child', kind, flush],
                                     env={**os.environ, 'PYTHONFAULTHANDLER': '1'}, capture_output=True,
                                     text=True, encoding='utf-8', errors='replace', timeout=60, check=False)
            print(f'{kind} {flush}: exit={process.returncode}', flush=True)
            print(process.stdout[-3000:], flush=True)
            if process.returncode:
                failed += 1
                print(process.stderr[-3000:], flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
