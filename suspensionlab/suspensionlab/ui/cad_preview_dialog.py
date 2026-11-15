"""Экспериментальный просмотр CAD-граней без связи с расчётным проектом."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.cad_measurement import measurement_distance
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
        self._mesh: CadMesh | None = None
        self._instance_counts: np.ndarray | None = None
        self._measurement_points: list[tuple[float, float, float]] = []
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
        self._deviation.setValue(10.)
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
        parts_row = QHBoxLayout()
        parts_row.addWidget(QLabel(tr("cad_preview.parts_label"), self))
        self._parts = QComboBox(self)
        self._parts.addItem(tr("cad_preview.parts_all"), -1)
        self._parts.setEnabled(False)
        self._parts.currentIndexChanged.connect(self._select_part)
        parts_row.addWidget(self._parts, 1)
        layout.addLayout(parts_row)
        instances_row = QHBoxLayout()
        instances_row.addWidget(QLabel(tr("cad_preview.instances_label"), self))
        self._instances = QComboBox(self)
        self._instances.addItem(tr("cad_preview.instances_all"), 0)
        self._instances.setEnabled(False)
        self._instances.currentIndexChanged.connect(self._select_instance)
        instances_row.addWidget(self._instances, 1)
        layout.addLayout(instances_row)
        self._context = QCheckBox(tr("cad_preview.highlight_context"), self)
        self._context.setEnabled(False)
        self._context.toggled.connect(self._select_instance)
        layout.addWidget(self._context)
        self._through = QCheckBox(tr("cad_preview.highlight_through"), self)
        self._through.setEnabled(False)
        self._through.toggled.connect(self._select_instance)
        layout.addWidget(self._through)
        measure_row = QHBoxLayout()
        self._measure = QCheckBox(tr("cad_preview.measure_mode"), self)
        self._measure.setEnabled(False)
        self._clear_measure = QPushButton(tr("cad_preview.measure_clear"), self)
        self._clear_measure.setEnabled(False)
        self._clear_measure.clicked.connect(self._clear_measurement)
        measure_row.addWidget(self._measure)
        measure_row.addStretch(1)
        measure_row.addWidget(self._clear_measure)
        layout.addLayout(measure_row)
        self._view = CadPreview(self)
        self._measure.toggled.connect(self._view.set_measure_mode)
        self._view.point_picked.connect(self._add_measurement_point)
        self._view.point_missed.connect(self._measurement_missed)
        self._view.triangle_picked.connect(self._pick_triangle)
        self._reset.clicked.connect(self._view.reset_camera)
        layout.addWidget(self._view, 1)
        self._status = QLabel(tr("cad_preview.empty"), self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._measurement = QLabel(tr("cad_preview.measure_warning"), self)
        self._measurement.setWordWrap(True)
        self._measurement.setMinimumHeight(self._measurement.fontMetrics().lineSpacing() * 4)
        self._measurement.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._measurement)
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
        self._measure.setChecked(False)
        self._measure.setEnabled(False)
        self._clear_measurement()
        self._mesh = None
        self._instance_counts = None
        self._parts.blockSignals(True)
        self._parts.clear()
        self._parts.addItem(tr("cad_preview.parts_all"), -1)
        self._parts.blockSignals(False)
        self._parts.setEnabled(False)
        self._clear_instances()
        self._context.setEnabled(False)
        self._through.setEnabled(False)
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
        self._mesh = mesh
        self._measure.setEnabled(True)
        self._instance_counts = (np.bincount(mesh.triangle_instances, minlength=len(mesh.instance_groups))
                                 if mesh.triangle_instances is not None else None)
        self._parts.blockSignals(True)
        self._parts.clear()
        self._parts.addItem(tr("cad_preview.parts_all"), -1)
        if mesh.triangle_parts is not None:
            counts = np.bincount(mesh.triangle_parts, minlength=len(mesh.part_names))
            for group, name in enumerate(mesh.part_names):
                if counts[group]:
                    self._parts.addItem(f"{name} · {group + 1}", group)
        self._parts.setCurrentIndex(0)
        self._parts.blockSignals(False)
        self._parts.setEnabled(self._parts.count() > 1)
        self._clear_instances()
        self._context.setEnabled(False)
        self._through.setEnabled(False)
        self._view.set_mesh(mesh)
        if mesh.skipped_faces or mesh.recovered_faces:
            self._status.setText(tr("cad_preview.approximate", faces=mesh.face_count,
                                    skipped=mesh.skipped_faces, recovered=mesh.recovered_faces,
                                    triangles=len(mesh.triangles)))
        else:
            self._status.setText(tr("cad_preview.loaded", faces=mesh.face_count, triangles=len(mesh.triangles)))

    def _update_measurement(self, missed: bool = False) -> None:
        lines = [tr("cad_preview.measure_warning")]
        values = []
        for label, point in zip(("A", "B"), self._measurement_points, strict=False):
            coords = ", ".join(f"{value:.2f}" for value in point)
            values.append(tr("cad_preview.measure_point", label=label, coords=coords))
        if len(self._measurement_points) == 2:
            length = measurement_distance(*self._measurement_points)
            values.append(tr("cad_preview.measure_distance", value=f"{length:.2f}"))
        if values:
            lines.append("   ·   ".join(values))
        if missed:
            lines.append(tr("cad_preview.measure_missed"))
        self._measurement.setText("\n".join(lines))
        self._clear_measure.setEnabled(bool(self._measurement_points))
        self._view.set_markers(tuple(self._measurement_points))

    def _clear_measurement(self) -> None:
        self._measurement_points.clear()
        self._update_measurement()

    def _add_measurement_point(self, point: tuple[float, float, float]) -> None:
        if len(self._measurement_points) == 2:
            self._measurement_points.clear()
        self._measurement_points.append(point)
        self._update_measurement()

    def _measurement_missed(self) -> None:
        self._update_measurement(missed=True)

    def _clear_instances(self) -> None:
        self._instances.blockSignals(True)
        self._instances.clear()
        self._instances.addItem(tr("cad_preview.instances_all"), 0)
        self._instances.blockSignals(False)
        self._instances.setEnabled(False)

    def _populate_instances(self) -> None:
        self._clear_instances()
        if self._mesh is None:
            return
        group = self._parts.currentData()
        if isinstance(group, int) and group >= 0 and self._instance_counts is not None:
            self._instances.blockSignals(True)
            number = 0
            for instance, parent in enumerate(self._mesh.instance_groups):
                if instance and parent == group and self._instance_counts[instance]:
                    number += 1
                    self._instances.addItem(tr("cad_preview.instance_number", number=number), instance)
            self._instances.blockSignals(False)
            self._instances.setEnabled(number > 0)

    def _select_part(self) -> None:
        self._populate_instances()
        self._select_instance()

    def _pick_triangle(self, index: int) -> None:
        mesh = self._mesh
        if mesh is None or self._view.mesh is not mesh or mesh.triangle_parts is None or not 0 <= index < len(mesh.triangles):
            return
        group = int(mesh.triangle_parts[index])
        instance = int(mesh.triangle_instances[index]) if mesh.triangle_instances is not None else 0
        part_index = self._parts.findData(group)
        if part_index < 0:
            return
        self._parts.blockSignals(True)
        self._parts.setCurrentIndex(part_index)
        self._parts.blockSignals(False)
        self._populate_instances()
        instance_index = self._instances.findData(instance)
        self._instances.blockSignals(True)
        self._instances.setCurrentIndex(max(0, instance_index))
        self._instances.blockSignals(False)
        self._context.blockSignals(True)
        self._context.setChecked(True)
        self._context.blockSignals(False)
        self._select_instance()

    def _select_instance(self) -> None:
        if self._mesh is None:
            return
        group = self._parts.currentData()
        instance = self._instances.currentData()
        selected = isinstance(group, int) and group >= 0 and self._mesh.triangle_parts is not None
        self._context.setEnabled(selected)
        context = selected and self._context.isChecked()
        self._through.setEnabled(context)
        if context:
            if isinstance(instance, int) and instance > 0 and self._mesh.triangle_instances is not None:
                highlight = self._mesh.triangle_instances == instance
            else:
                highlight = self._mesh.triangle_parts == group
            self._view.set_mesh(self._mesh, highlight, self._through.isChecked())
        elif group == -1:
            self._view.set_mesh(self._mesh)
        elif isinstance(instance, int) and instance > 0:
            self._view.set_mesh(self._mesh.isolated_instance(instance))
        elif isinstance(group, int):
            self._view.set_mesh(self._mesh.isolated(group))

    def _show_error(self, code: str) -> None:
        self._measure.setChecked(False)
        self._measure.setEnabled(False)
        self._clear_measurement()
        self._mesh = None
        self._instance_counts = None
        self._parts.setEnabled(False)
        self._clear_instances()
        self._context.setEnabled(False)
        self._through.setEnabled(False)
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
