"""Асинхронный частичный просмотр двух труб; старые результаты не показываются."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.cad_mesh import CadMesh
from ..core.cad_transport import CadPreviewError
from ..core.cad_weldment_job import WeldmentCadJob
from ..i18n import tr
from .canvas.cad_preview import CadPreview


class _TubeReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], token: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.document = document
        self.token = token
        self.job = WeldmentCadJob()

    def run(self) -> None:
        try:
            self.completed.emit(self.token, self.job.run(self.document))
        except CadPreviewError as error:
            self.failed.emit(self.token, error.code)
        except Exception:
            self.failed.emit(self.token, "unexpected")


class Weldment3D(QWidget):
    availabilityChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None, *,
                 is_current: Callable[[dict[str, Any]], bool] | None = None,
                 single_tube: bool = False) -> None:
        super().__init__(parent)
        self._is_current = is_current
        self._single_tube = single_tube
        self._document: dict[str, Any] | None = None
        self._pending: dict[str, Any] | None = None
        self._worker: _TubeReader | None = None
        self._ready = False
        self._closed = False
        self.generation = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._start)
        layout = QVBoxLayout(self)
        self._enable = QCheckBox(tr("rear_tube.enable" if single_tube else "weldment_3d.enable"), self)
        self._enable.toggled.connect(self._toggle)
        layout.addWidget(self._enable)
        self._status = QLabel(tr("weldment_3d.off"), self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._view = CadPreview(self, empty_text_key="weldment_3d.empty")
        layout.addWidget(self._view, 1)
        self._retry = QPushButton(tr("weldment_3d.retry"), self)
        self._retry.setEnabled(False)
        self._retry.clicked.connect(self._restart)
        layout.addWidget(self._retry)
        self._reset = QPushButton(tr("weldment_3d.reset"), self)
        self._reset.clicked.connect(self._view.reset_camera)
        layout.addWidget(self._reset)

    def can_save(self) -> bool:
        return not self._closed and (not self._enable.isChecked() or self._ready)

    def _toggle(self, _checked: bool) -> None:
        self._schedule()

    def _restart(self) -> None:
        self._schedule()

    def set_document(self, document: dict[str, Any] | None) -> None:
        self._document = document
        self._schedule()

    def _schedule(self) -> None:
        self.generation += 1
        self._ready = False
        self._pending = None
        self._timer.stop()
        self._view.set_mesh(None)
        self._retry.setEnabled(False)
        if self._worker is not None:
            self._worker.job.cancel()
        if self._closed:
            self._status.setText(tr("weldment_3d.closing"))
        elif not self._enable.isChecked():
            self._status.setText(tr("weldment_3d.off"))
        elif self._document is None:
            self._status.setText(tr("weldment_3d.no_data"))
        else:
            self._pending = self._document
            self._status.setText(tr("rear_tube.building" if self._single_tube else "weldment_3d.building"))
            self._timer.start()
        self.availabilityChanged.emit(self.can_save())

    def _start(self) -> None:
        if self._worker is not None or self._pending is None or self._closed:
            return
        document, self._pending = self._pending, None
        worker = _TubeReader(document, self.generation, self)
        self._worker = worker
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    def _completed(self, token: int, mesh: object) -> None:
        if token != self.generation or self._closed or not self._enable.isChecked() or self._document is None:
            return
        if self._is_current is not None and not self._is_current(self._document):
            self._failed(token, "changed")
            return
        if not isinstance(mesh, CadMesh) or mesh.skipped_faces or mesh.recovered_faces:
            self._failed(token, "mesh")
            return
        self._view.set_mesh(mesh)
        self._ready = True
        self._retry.setEnabled(True)
        self._status.setText(tr("rear_tube.cad_ready" if self._single_tube else "weldment_3d.ready",
                                triangles=len(mesh.triangles)))
        self.availabilityChanged.emit(self.can_save())

    def _failed(self, token: int, code: str) -> None:
        if token != self.generation or self._closed:
            return
        known = {"missing_cad", "timeout", "cancelled", "start", "crash", "mesh", "memory",
                 "missing_face", "coordinates", "no_faces", "no_shape", "output", "unexpected", "changed"}
        if code not in known:
            code = "unexpected"
        self._ready = False
        self._view.set_mesh(None)
        self._retry.setEnabled(self._document is not None and self._enable.isChecked())
        specific = {"timeout", "memory", "changed"}
        reason = tr(f"weldment_3d.error_{code}") if code in specific else tr(f"cad_preview.error.{code}")
        self._status.setText(tr("weldment_3d.failed", reason=reason))
        self.availabilityChanged.emit(self.can_save())

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        if self._pending is not None and not self._closed:
            self._timer.start()

    def shutdown(self) -> bool:
        """Остановить процесс перед уничтожением Qt-объектов; False — ещё завершается."""
        if not self._closed:
            self._closed = True
            self._schedule()
        if self._worker is None:
            return True
        self._worker.job.cancel()
        return bool(self._worker.wait(3000))
