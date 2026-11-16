"""Временный просмотр CAD-сетки и пар пробного совмещения в системе проекта."""
from __future__ import annotations

from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from ..core.cad_mesh import CadMesh
from ..core.cad_registration_overlay import OverlayPair, transform_mesh_for_preview
from ..core.spatial_transform import RigidTransform
from ..i18n import tr
from .cad_preview_dialog import _CadReader
from .cad_preview_settings import read_cad_deviation
from .canvas.cad_registration_overlay import RegistrationOverlayCanvas
from .controller import AppController
from .widgets.camera_views import CameraViews


class CadRegistrationOverlayDialog(QDialog):
    def __init__(self, controller: AppController, transform: RigidTransform, pairs: tuple[OverlayPair, ...],
                 settings, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.transform, self.pairs = transform, pairs
        self._deviation = read_cad_deviation(settings)
        self._reader: _CadReader | None = None
        self._stale = False
        self._closing = False
        self._discard_result = False
        self._progress_stage = "read"
        self._progress_faces = 0
        self._progress_started = 0.0
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._refresh_progress)
        self.setWindowTitle(tr("cad_registration_overlay.title"))
        self.resize(1100, 760)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        layout = QVBoxLayout(self)
        notice = QLabel(tr("cad_registration_overlay.notice"), self)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self._confirm = QCheckBox(tr("cad_registration_overlay.confirm"), self)
        self._confirm.toggled.connect(self._confirm_changed)
        layout.addWidget(self._confirm)
        controls = QHBoxLayout()
        self._choose = QPushButton(tr("cad_registration_overlay.choose"), self)
        self._choose.setEnabled(False)
        self._choose.clicked.connect(self._choose_file)
        self._cancel = QPushButton(tr("cad_preview.cancel"), self)
        self._cancel.setEnabled(False)
        self._cancel.clicked.connect(self._cancel_read)
        self._filter = QComboBox(self)
        for key in ("all", "fit", "control"):
            self._filter.addItem(tr(f"cad_registration_overlay.filter_{key}"), key)
        self._filter.currentIndexChanged.connect(self._populate)
        controls.addWidget(self._choose)
        controls.addWidget(self._cancel)
        controls.addWidget(self._filter)
        controls.addStretch()
        self._views = CameraViews(self, cad=True)
        controls.addWidget(self._views)
        self._reset = QPushButton(tr("cad_preview.reset"), self)
        controls.addWidget(self._reset)
        layout.addLayout(controls)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._list = QListWidget(splitter)
        self._list.setMinimumWidth(210)
        self._canvas = RegistrationOverlayCanvas(pairs, splitter)
        self._views.viewSelected.connect(self._canvas.set_standard_view)
        self._reset.clicked.connect(self._canvas.reset_camera)
        splitter.addWidget(self._list)
        splitter.addWidget(self._canvas)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 720])
        layout.addWidget(splitter, 1)
        self._detail = QLabel(self)
        self._detail.setWordWrap(True)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._detail)
        self._progress_label = QLabel(self)
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setTextVisible(False)
        self._progress_label.hide()
        self._progress_bar.hide()
        layout.addWidget(self._progress_label)
        layout.addWidget(self._progress_bar)
        self._status = QLabel(tr("cad_registration_overlay.empty"), self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        close = QPushButton(tr("point_table.close"), self)
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._list.currentItemChanged.connect(self._selection_changed)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._invalidate)
        self._populate()

    def _confirm_changed(self) -> None:
        self._choose.setEnabled(self._confirm.isChecked() and self._reader is None and not self._stale)
        if not self._confirm.isChecked():
            self._discard_result = True
            self._canvas.set_mesh(None)
            if self._reader is not None:
                self._reader.job.cancel()
            if not self._stale:
                self._status.setText(tr("cad_registration_overlay.empty"))

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("cad_registration_overlay.choose"), "", tr("step_inventory.filter"))
        if path and not self._stale and self._confirm.isChecked() and self._reader is None:
            self.load_file(Path(path))

    def load_file(self, path: Path) -> None:
        if self._stale or not self._confirm.isChecked() or self._reader is not None:
            return
        self._discard_result = False
        self._canvas.set_mesh(None)
        self._status.setText(tr("cad_preview.loading"))
        self._choose.setEnabled(False)
        self._cancel.setEnabled(True)
        self._progress_stage, self._progress_faces = "read", 0
        self._progress_started = monotonic()
        self._progress_label.show()
        self._progress_bar.show()
        self._refresh_progress()
        self._progress_timer.start()
        reader = _CadReader(path, self._deviation, self)
        self._reader = reader
        reader.result_ready.connect(self._show_mesh)
        reader.failed.connect(self._show_error)
        reader.progress.connect(self._update_progress)
        reader.finished.connect(self._finished)
        reader.start()

    def _update_progress(self, stage: str, faces: int) -> None:
        self._progress_stage, self._progress_faces = stage, faces
        self._refresh_progress()

    def _refresh_progress(self) -> None:
        elapsed = max(0, int(monotonic() - self._progress_started))
        stage = tr(f"cad_preview.progress_{self._progress_stage}")
        if self._progress_stage in ("faces", "save"):
            stage += tr("cad_preview.progress_faces_count", count=self._progress_faces)
        self._progress_label.setText(tr("cad_preview.progress_label", stage=stage, seconds=elapsed))

    def _show_mesh(self, mesh: CadMesh) -> None:
        if self._stale or self._closing or self._discard_result or not self._confirm.isChecked():
            return
        try:
            result = transform_mesh_for_preview(mesh, self.transform)
        except ValueError:
            self._canvas.set_mesh(None)
            self._status.setText(tr("cad_registration_overlay.coordinates_error"))
            return
        self._canvas.set_mesh(result)
        self._canvas.fit_overlay_bounds()
        self._canvas.reset_camera()
        self._status.setText(tr("cad_registration_overlay.loaded", faces=mesh.face_count,
                                triangles=len(mesh.triangles), skipped=mesh.skipped_faces,
                                recovered=mesh.recovered_faces, deviation=f"{self._deviation:.1f}"))

    def _show_error(self, code: str) -> None:
        if self._stale or self._closing or self._discard_result or not self._confirm.isChecked():
            return
        known = {"cancelled", "start", "timeout", "crash", "file_size", "deviation", "missing_cad", "units",
                 "read", "no_shape", "mesh", "limit", "memory", "missing_face", "coordinates", "no_faces", "unexpected", "output"}
        self._status.setText(tr(f"cad_preview.error.{code if code in known else 'unexpected'}"))

    def _cancel_read(self) -> None:
        if self._reader is not None:
            self._cancel.setEnabled(False)
            self._discard_result = True
            self._reader.job.cancel()
            self._status.setText(tr("cad_preview.cancelling"))

    def _finished(self) -> None:
        self._progress_timer.stop()
        self._progress_label.hide()
        self._progress_bar.hide()
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.deleteLater()
        self._cancel.setEnabled(False)
        self._choose.setEnabled(not self._stale and self._confirm.isChecked())
        if self._discard_result and not self._stale and not self._closing:
            self._status.setText(tr("cad_registration_overlay.empty"))
        if self._closing:
            super().reject()

    def _invalidate(self) -> None:
        self._stale = True
        self._discard_result = True
        if self._reader is not None:
            self._reader.job.cancel()
        self._canvas.set_mesh(None)
        self._canvas.setEnabled(False)
        self._confirm.setEnabled(False)
        self._choose.setEnabled(False)
        self._cancel.setEnabled(False)
        self._filter.setEnabled(False)
        self._list.setEnabled(False)
        self._status.setText(tr("cad_registration.stale"))

    def _populate(self, *_args) -> None:
        filter_key = self._filter.currentData()
        current = self._list.currentItem()
        previous = current.data(Qt.ItemDataRole.UserRole) if current else -1
        self._list.blockSignals(True)
        self._list.clear()
        visible = []
        for index, pair in enumerate(self.pairs):
            if filter_key == "fit" and not pair.fit or filter_key == "control" and pair.fit:
                continue
            visible.append(index)
            purpose = tr("cad_registration.fit" if pair.fit else "cad_registration.control")
            item = QListWidgetItem(f"{pair.row}. {pair.role} / {pair.code} — {purpose}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self._list.addItem(item)
            if index == previous:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)
        self._canvas.visible = frozenset(visible)
        self._selection_changed()

    def _selection_changed(self, *_args) -> None:
        item = self._list.currentItem()
        index = item.data(Qt.ItemDataRole.UserRole) if item else -1
        self._canvas.selected = index
        self._canvas.update()
        if index < 0:
            self._detail.setText(tr("cad_registration_overlay.legend"))
            return
        pair = self.pairs[index]
        self._detail.setText(tr("cad_registration_overlay.detail", row=pair.row, role=pair.role,
                                code=pair.code, distance=f"{pair.distance_mm:.6g}"))

    def reject(self) -> None:
        if self._reader is not None:
            self._closing = True
            self._discard_result = True
            self._reader.job.cancel()
            self._choose.setEnabled(False)
            self._cancel.setEnabled(False)
            self._status.setText(tr("cad_preview.cancelling"))
        else:
            super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._reader is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
