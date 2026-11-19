"""Запускает каждый повтор Qt/CAD в свежем процессе, сохраняя вывод и код выхода."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path


def main() -> int:
    from PySide6.QtCore import qVersion

    output = Path('qt-cad-diagnostics')
    output.mkdir(exist_ok=True)
    metadata = {
        'revision': os.environ.get('DIAGNOSTIC_SHA', 'unknown'),
        'variant': os.environ.get('DIAGNOSTIC_VARIANT', 'unknown'),
        'platform': platform.platform(), 'python': sys.version,
        'pyside': version('PySide6-Essentials'), 'qt': qVersion(),
        'ocp': version('cadquery-ocp-novtk'), 'numpy': version('numpy'),
        'pytest': version('pytest'), 'pytest_qt': version('pytest-qt'),
        'qt_qpa_platform': os.environ.get('QT_QPA_PLATFORM'),
    }
    results = []
    for index in range(1, 4):
        logfile = output / f'iteration-{index}.log'
        junit = output / f'iteration-{index}.xml'
        command = [sys.executable, '-m', 'pytest', '-v', '-s', '-o', 'faulthandler_timeout=60',
                   '--junitxml', str(junit), 'diagnostics/test_qt_cad_lifecycle.py']
        started = time.monotonic()
        with logfile.open('wb') as stream:
            try:
                process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                         env={**os.environ, 'PYTHONFAULTHANDLER': '1', 'PYTHONUTF8': '1'},
                                         timeout=240, check=False)
                code: int | str = process.returncode
            except subprocess.TimeoutExpired:
                code = 'timeout'
        record = {'iteration': index, 'returncode': code, 'seconds': round(time.monotonic() - started, 2)}
        results.append(record)
        print(json.dumps(record), flush=True)
        if code != 0:
            text = logfile.read_text(encoding='utf-8', errors='replace')[-16000:]
            print(text, flush=True)
            escaped = text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print(f'::error title=Qt CAD iteration {index}::{escaped}', flush=True)
    (output / 'summary.json').write_text(json.dumps({'environment': metadata, 'results': results},
                                                    indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if all(result['returncode'] == 0 for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
