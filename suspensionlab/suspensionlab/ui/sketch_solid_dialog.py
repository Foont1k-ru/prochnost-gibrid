"""Отменяемое построение STEP в отдельном CAD-процессе."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..core.sketch_solid_job import SketchSolidError, SketchSolidJob
from ..model.sketch_io import SketchDocument


class _SolidWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, document: SketchDocument, depth: float, destination: Path, parent: QWidget,
                 direction: str = "positive", hole_depth: float = 0, hole_side: str = "auto") -> None:
        super().__init__(parent)
        self.document, self.depth, self.destination, self.direction = document, depth, destination, direction
        self.hole_depth, self.hole_side = hole_depth, hole_side
        self.job = SketchSolidJob()

    def run(self) -> None:
        try:
            self.completed.emit(self.job.run(self.document, self.depth, self.destination, direction=self.direction,
                                             hole_depth=self.hole_depth, hole_side=self.hole_side))
        except SketchSolidError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Непредвиденная ошибка построения тела")


class SketchSolidDialog(QDialog):
    def __init__(self, document: SketchDocument, depth: float, destination: Path,
                 parent: QWidget | None = None, *, direction: str = "positive", hole_depth: float = 0, hole_side: str = "auto") -> None:
        super().__init__(parent)
        self.setWindowTitle("Создание CAD-тела")
        self.setModal(True)
        self.output: Path | None = None
        self.error: str | None = None
        self.cancel_requested = False
        self._done = False
        layout = QVBoxLayout(self)
        self.status = QLabel("CAD-ядро строит тело и записывает новый STEP. Эскиз и проект не изменяются.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        progress = QProgressBar()
        progress.setRange(0, 0)
        layout.addWidget(progress)
        self.cancel_button = QPushButton("Отменить построение")
        self.cancel_button.clicked.connect(self._cancel)
        layout.addWidget(self.cancel_button)
        self.worker = _SolidWorker(document, depth, destination, self, direction, hole_depth, hole_side)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)

    def start(self) -> None:
        self.worker.start()

    def _completed(self, result: Path) -> None:
        self.output = result

    def _failed(self, message: str) -> None:
        self.error = message

    def _finished(self) -> None:
        self._done = True
        super().accept()

    def _cancel(self) -> None:
        self.cancel_requested = True
        self.status.setText("Отменяем построение…")
        self.cancel_button.setEnabled(False)
        self.worker.job.cancel()

    def reject(self) -> None:
        if not self._done:
            self._cancel()
        else:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._done:
            self._cancel()
            event.ignore()
        else:
            super().closeEvent(event)
