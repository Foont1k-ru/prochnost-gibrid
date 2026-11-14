"""Экспериментальный просмотр CAD-граней без связи с расчётным проектом."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.cad_mesh import CadMesh
from ..core.cad_transport import CadJob, CadPreviewError
from ..i18n import tr
from .canvas.cad_preview import CadPreview


class _CadReader(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path, deviation: float, parent: QDialog) -> None:
        super().__init__(parent)
        self.path, self.deviation = path, deviation
        self.job = CadJob()

    def run(self) -> None:
        try:
            self.result_ready.emit(self.job.run(self.path, self.deviation))
        except CadPreviewError as error:
            self.failed.emit(error.code)
        except Exception:
            self.failed.emit("unexpected")


class CadPreviewDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("cad_preview.title"))
        self.resize(960, 750)
        self._reader: _CadReader | None = None
        self._path: Path | None = None
        layout = QVBoxLayout(self)
        notice = QLabel(tr("cad_preview.notice"), self)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        row = QHBoxLayout()
        self._choose = QPushButton(tr("cad_preview.choose"), self)
        self._choose.clicked.connect(self._choose_file)
        self._deviation = QDoubleSpinBox(self)
        self._deviation.setRange(0.2, 20.)
        self._deviation.setDecimals(1)
        self._deviation.setValue(2.)
        self._deviation.setSingleStep(0.5)
        self._deviation.setSuffix(tr("cad_preview.mm"))
        self._reload = QPushButton(tr("cad_preview.reload"), self)
        self._reload.setEnabled(False)
        self._reload.clicked.connect(self._reload_file)
        self._cancel = QPushButton(tr("cad_preview.cancel"), self)
        self._cancel.setEnabled(False)
        self._cancel.clicked.connect(self._cancel_read)
        self._reset = QPushButton(tr("cad_preview.reset"), self)
        row.addWidget(self._choose)
        row.addWidget(QLabel(tr("cad_preview.deviation"), self))
        row.addWidget(self._deviation)
        row.addWidget(self._reload)
        row.addWidget(self._cancel)
        row.addWidget(self._reset)
        layout.addLayout(row)
        self._view = CadPreview(self)
        self._reset.clicked.connect(self._view.reset_camera)
        layout.addWidget(self._view, 1)
        self._status = QLabel(tr("cad_preview.empty"), self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("cad_preview.choose"), "", tr("step_inventory.filter"))
        if path:
            self.load_file(Path(path))

    def _reload_file(self) -> None:
        if self._path is not None:
            self.load_file(self._path)

    def load_file(self, path: Path) -> None:
        if self._reader is not None:
            return
        self._path = path
        self._view.set_mesh(None)
        self._status.setText(tr("cad_preview.loading"))
        self._choose.setEnabled(False)
        self._reload.setEnabled(False)
        self._deviation.setEnabled(False)
        self._buttons.setEnabled(False)
        self._cancel.setEnabled(True)
        reader = _CadReader(path, self._deviation.value(), self)
        self._reader = reader
        reader.result_ready.connect(self._show_mesh)
        reader.failed.connect(self._show_error)
        reader.finished.connect(self._finished)
        reader.start()

    def _show_mesh(self, mesh: CadMesh) -> None:
        self._view.set_mesh(mesh)
        self._status.setText(tr("cad_preview.loaded", faces=mesh.face_count, triangles=len(mesh.triangles)))

    def _show_error(self, code: str) -> None:
        self._view.set_mesh(None)
        self._status.setText(tr(f"cad_preview.error.{code}"))

    def _cancel_read(self) -> None:
        if self._reader is not None:
            self._cancel.setEnabled(False)
            self._status.setText(tr("cad_preview.cancelling"))
            self._reader.job.cancel()

    def _finished(self) -> None:
        reader = self._reader
        self._reader = None
        if reader is not None:
            reader.deleteLater()
        self._choose.setEnabled(True)
        self._reload.setEnabled(self._path is not None)
        self._deviation.setEnabled(True)
        self._buttons.setEnabled(True)
        self._cancel.setEnabled(False)

    def reject(self) -> None:
        if self._reader is None:
            super().reject()
        else:
            self._cancel_read()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._reader is not None:
            self._cancel_read()
            event.ignore()
        else:
            super().closeEvent(event)
