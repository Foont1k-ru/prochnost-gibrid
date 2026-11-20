"""Необязательная изолированная проверка объёма пересечения двух труб."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.cad_fixed_arm_overlap_job import FixedArmOverlapJob, OverlapJobError, OverlapResult


class _OverlapReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], token: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.document = document
        self.token = token
        self.job = FixedArmOverlapJob()

    def run(self) -> None:
        try:
            self.completed.emit(self.token, self.job.run(self.document))
        except OverlapJobError as error:
            self.failed.emit(self.token, str(error))
        except Exception:
            self.failed.emit(self.token, 'unexpected')


class FixedArmOverlap(QWidget):
    def __init__(self, is_current: Callable[[dict[str, Any]], bool], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_current = is_current
        self._document: dict[str, Any] | None = None
        self._worker: _OverlapReader | None = None
        self._closed = False
        self.generation = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._button = QPushButton('Проверить пересечение двух труб', self)
        self._button.setEnabled(False)
        self._button.clicked.connect(self._start)
        layout.addWidget(self._button)
        self._status = QLabel('Проверка не запускалась. Касание, зазоры и прочность не определяются.', self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    def set_document(self, document: dict[str, Any] | None) -> None:
        self.generation += 1
        self._document = document
        if self._worker is not None:
            self._worker.job.cancel()
        self._button.setEnabled(not self._closed and document is not None and self._worker is None)
        self._status.setText('Проверка не запускалась для текущих параметров. '
                             'Касание, зазоры и прочность не определяются.')

    def _start(self) -> None:
        if self._closed or self._worker is not None or self._document is None:
            return
        if not self._is_current(self._document):
            self._status.setText('Снимок устарел; повторите фиксацию и проверку.')
            return
        worker = _OverlapReader(self._document, self.generation, self)
        self._worker = worker
        self._button.setEnabled(False)
        self._status.setText('Проверка двух труб выполняется в отдельном процессе…')
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    def _completed(self, token: int, result: object) -> None:
        if token != self.generation or self._closed or self._document is None:
            return
        if not self._is_current(self._document):
            self._status.setText('Снимок устарел; результат скрыт.')
            return
        if not isinstance(result, OverlapResult):
            self._failed(token, 'output')
            return
        if result.overlap_mm3 > result.threshold_mm3:
            finding = f'Обнаружено объёмное пересечение труб: примерно {result.overlap_mm3:.6g} мм³.'
        else:
            finding = (f'Объёмного пересечения выше численного порога {result.threshold_mm3:.3g} мм³ '
                       'не обнаружено.')
        self._status.setText(finding + ' Это не проверка касания, минимального зазора, сварки или прочности; '
                             'корпуса и другие детали не проверяются.')

    def _failed(self, token: int, code: str) -> None:
        if token != self.generation or self._closed:
            return
        if self._document is None or not self._is_current(self._document):
            self._status.setText('Снимок устарел; результат скрыт.')
            return
        reason = 'превышено время' if code == 'timeout' else 'не удалось построить или проверить детали'
        self._status.setText(f'Проверка не выполнена: {reason}. Достоверного результата нет.')

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._button.setEnabled(not self._closed and self._document is not None)

    def shutdown(self) -> bool:
        self._closed = True
        self.generation += 1
        self._document = None
        self._button.setEnabled(False)
        if self._worker is None:
            return True
        self._worker.job.cancel()
        return bool(self._worker.wait(3000))
