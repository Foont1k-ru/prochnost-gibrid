"""Изолированный опыт удаления окон Qt при сборке циклов в другом потоке.

Запуск без аргументов создаёт отдельный процесс для каждого варианта. Опасный
вариант намеренно воспроизводит неправильный жизненный цикл и может завершиться
нативным сбоем: никогда не вызывать его внутри процесса приложения или pytest.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


def child(mode: str) -> int:
    if mode == 'unsafe' and os.name == 'posix':
        # Искусственная авария не должна создавать большой дамп памяти пользователя.
        import resource

        _, hard = resource.getrlimit(resource.RLIMIT_CORE)
        resource.setrlimit(resource.RLIMIT_CORE, (0, hard))

    from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
    from PySide6.QtWidgets import QApplication

    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.joint_concept_dialog import JointConceptDialog
    from suspensionlab.ui.main_window import MainWindow

    app = QApplication([])
    gc.disable()
    main_ident = threading.get_ident()
    destroyed_threads: list[int] = []
    controller = AppController()
    with tempfile.TemporaryDirectory(prefix='suspension-qt-gc-probe-') as temp:
        window = (MainWindow(controller, QSettings(str(Path(temp) / 'settings.ini'), QSettings.Format.IniFormat))
                  if mode == 'managed' else None)
        retained = []
        for _ in range(20):
            if window is None:
                dialog = JointConceptDialog(controller)
            else:
                window._open_joint_concept()
                dialog = window._joint_concept_dialog
                assert dialog is not None
            dialog.destroyed.connect(
                lambda *_args: destroyed_threads.append(threading.get_ident()), Qt.ConnectionType.DirectConnection
            )
            assert dialog.close()
            if mode == 'explicit':
                retained.append(dialog)
                dialog.deleteLater()
            del dialog

        if mode == 'explicit':
            # Сохраняем Python-ссылки до обработки DeferredDelete в GUI-потоке.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            if len(destroyed_threads) != 20 or any(ident != main_ident for ident in destroyed_threads):
                raise RuntimeError('explicitly retained dialogs were not destroyed on the GUI thread')
            retained.clear()

        def collect() -> None:
            gc.collect()

        thread = threading.Thread(target=collect)
        thread.start()
        thread.join()
        before_events = len(destroyed_threads)
        outside_main = sum(ident != main_ident for ident in destroyed_threads)
        # Печатаем наблюдение до обработки событий: в unsafe она может вызвать SIGSEGV.
        print('GC_PROBE ' + json.dumps({'mode': mode, 'before_events': before_events,
                                        'outside_main': outside_main}), flush=True)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        if window is not None:
            if len(destroyed_threads) != 20 or any(ident != main_ident for ident in destroyed_threads):
                raise RuntimeError('managed dialogs were not destroyed on the GUI thread')
            assert window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.enable()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=('unsafe', 'managed', 'explicit'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args.child)
    valid = True
    for mode in ('unsafe', 'managed', 'explicit'):
        process = subprocess.run([sys.executable, '-u', __file__, '--child', mode],
                                 env={**os.environ, 'PYTHONFAULTHANDLER': '1'}, capture_output=True,
                                 text=True, encoding='utf-8', errors='replace', timeout=60, check=False)
        print(f'{mode}: exit={process.returncode}', flush=True)
        observations = [line for line in process.stdout.splitlines() if line.startswith('GC_PROBE ')]
        for line in observations:
            print(line, flush=True)
        if process.returncode:
            print(process.stderr[-4000:], flush=True)
        # Авария допустима только после измерения в намеренно небезопасном варианте.
        valid = valid and bool(observations) and (mode == 'unsafe' or process.returncode == 0)
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
