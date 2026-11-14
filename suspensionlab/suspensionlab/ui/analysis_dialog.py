"""Первый табличный просмотр экспериментального расчёта двухрычажной оси."""
from __future__ import annotations

import logging
from math import isfinite
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.analysis import analyze_corner
from ..core.damper import LinearDamperCharacteristic, evaluate_linear_damping
from ..core.double_wishbone import DoubleWishbone
from ..core.pose_view import PoseView, pose_view
from ..core.stroke import StrokeLimits
from ..core.sweep import travel_grid
from ..i18n import tr
from .canvas.pose_preview import PosePreview
from .controller import AppController
from .table_export import make_table_report, save_table_dialog
from .widgets.playback import PlaybackControls

LOG = logging.getLogger(__name__)


class AnalysisDialog(QDialog):
    """Явный запуск анализа одной стороны, без изменения и сохранения проекта."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(tr("analysis.title"))
        self.resize(1200, 700)
        self._role = QComboBox(self)
        for role in ("front", "rear"):
            self._role.addItem(tr(f"tree.{role}"), role)
        self._side = QComboBox(self)
        for side in ("left", "right"):
            self._side.addItem(tr(f"hp.side.{side}"), side)
        self._from = self._number(-100, 100, -30, 1)
        self._to = self._number(-100, 100, 30, 1)
        self._step = self._number(0.1, 20, 1, 0.1)
        self._spring = QCheckBox(tr("analysis.spring_enable"), self)
        self._spring_length = self._number(0, 2000, 0, 1)
        self._coil_bind = self._number(0, 2000, 0, 1)
        self._damper = QCheckBox(tr("analysis.damper_enable"), self)
        self._damper_min = self._number(0, 2000, 0, 1)
        self._damper_max = self._number(0, 2000, 0, 1)
        self._damping = QCheckBox(tr("analysis.damping_enable"), self)
        self._velocity = QLineEdit(self)
        self._compression = QLineEdit(self)
        self._rebound = QLineEdit(self)
        for edit in (self._velocity, self._compression, self._rebound):
            edit.setPlaceholderText(tr("analysis.explicit_required"))
            edit.setMaximumWidth(110)

        fields = QHBoxLayout()
        geometry = QFormLayout()
        for label, widget in (("role", self._role), ("side", self._side), ("from", self._from),
                              ("to", self._to), ("step", self._step)):
            geometry.addRow(tr(f"analysis.{label}"), widget)
        spring = QFormLayout()
        spring.addRow(self._spring)
        spring.addRow(tr("analysis.spring_length"), self._spring_length)
        spring.addRow(tr("analysis.coil_bind"), self._coil_bind)
        damper = QFormLayout()
        damper.addRow(self._damper)
        damper.addRow(tr("analysis.damper_min"), self._damper_min)
        damper.addRow(tr("analysis.damper_max"), self._damper_max)
        fields.addLayout(geometry)
        fields.addLayout(spring)
        fields.addLayout(damper)

        self._notice = QLabel(tr("analysis.notice"), self)
        self._notice.setWordWrap(True)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._table = QTableWidget(0, 12, self)
        self._table.setHorizontalHeaderLabels([tr(f"analysis.column.{key}") for key in (
            "travel", "camber", "toe", "spring_length", "spring_compression", "spring_force",
            "damper_length", "damper_ratio", "state", "damper_speed", "damper_wheel_force", "damper_power",
        )])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._frames: list[PoseView | None] = []
        self._cambers: list[float] = []
        self._preview = PosePreview(self)
        self._preview_status = QLabel(tr("analysis.preview_empty"), self)
        self._preview_status.setWordWrap(True)
        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setEnabled(False)
        self._previous = QPushButton(tr("analysis.previous"), self)
        self._next = QPushButton(tr("analysis.next"), self)
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        navigation = QHBoxLayout()
        navigation.addWidget(self._previous)
        navigation.addWidget(self._slider, 1)
        navigation.addWidget(self._next)
        preview_container = QWidget(self)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self._preview, 1)
        preview_layout.addWidget(self._preview_status)
        preview_layout.addLayout(navigation)
        self._playback = PlaybackControls(self._table.currentRow, lambda row: self._table.setCurrentCell(row, 0),
                                          self._playback_problem, self)
        preview_layout.addWidget(self._playback)
        self._playback_reasons: list[str | None] = []
        self.finished.connect(lambda _result: self._playback.set_count(0))
        self._split = QSplitter(Qt.Orientation.Horizontal, self)
        self._split.addWidget(self._table)
        self._split.addWidget(preview_container)
        self._split.setSizes([700, 500])
        self._table.currentCellChanged.connect(self._show_row)
        self._slider.valueChanged.connect(lambda row: self._table.setCurrentCell(row, 0))
        self._previous.clicked.connect(lambda: self._slider.setValue(self._slider.value() - 1))
        self._next.clicked.connect(lambda: self._slider.setValue(self._slider.value() + 1))
        self._run = QPushButton(tr("analysis.run"), self)
        self._run.clicked.connect(self._calculate)
        self._export_button = QPushButton(tr("export.button"), self)
        self._export_button.clicked.connect(self._export)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("analysis.close"))
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(self._run)
        row.addWidget(self._export_button)
        row.addStretch()
        row.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.addWidget(self._notice)
        layout.addLayout(fields)
        dynamics = QHBoxLayout()
        dynamics.addWidget(self._damping)
        for key, edit in (("velocity", self._velocity), ("compression", self._compression), ("rebound", self._rebound)):
            dynamics.addWidget(QLabel(tr(f"analysis.{key}"), self))
            dynamics.addWidget(edit)
        dynamics.addStretch()
        layout.addLayout(dynamics)
        layout.addWidget(self._status)
        layout.addWidget(self._split, 1)
        layout.addLayout(row)

        for combo in (self._role, self._side):
            combo.currentIndexChanged.connect(self._invalidate)
        for field in (self._from, self._to, self._step, self._spring_length, self._coil_bind,
                      self._damper_min, self._damper_max):
            field.valueChanged.connect(self._invalidate)
        self._spring.toggled.connect(self._invalidate)
        self._damper.toggled.connect(self._invalidate)
        self._damping.toggled.connect(self._invalidate)
        for edit in (self._velocity, self._compression, self._rebound):
            edit.textChanged.connect(self._invalidate)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._invalidate)
        self._invalidate()

    def _number(self, minimum: float, maximum: float, value: float, step: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox(self)
        box.setRange(minimum, maximum)
        box.setDecimals(1)
        box.setSingleStep(step)
        box.setValue(value)
        return box

    def _clear_results(self) -> None:
        self._playback.set_count(0)
        self._export_button.setEnabled(False)
        self._frames = []
        self._cambers = []
        self._playback_reasons = []
        self._preview.clear()
        self._preview_status.setText(tr("analysis.preview_empty"))
        self._slider.setEnabled(False)
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        self._table.setRowCount(0)

    def _invalidate(self, *_args: object) -> None:
        self._clear_results()
        self._spring_length.setEnabled(self._spring.isChecked())
        self._coil_bind.setEnabled(self._spring.isChecked())
        self._damper_min.setEnabled(self._damper.isChecked())
        self._damper_max.setEnabled(self._damper.isChecked())
        if not self._damper.isChecked():
            self._damping.setChecked(False)
        self._damping.setEnabled(self._damper.isChecked())
        for field in (self._velocity, self._compression, self._rebound):
            field.setEnabled(self._damper.isChecked() and self._damping.isChecked())
        supported = self.controller.project.axle(str(self._role.currentData())).type_code == "double_wishbone"
        self._run.setEnabled(supported)
        self._status.setText(tr("analysis.ready" if supported else "analysis.unsupported"))

    def _calculate(self) -> None:
        self._clear_results()
        role = str(self._role.currentData())
        axle = self.controller.project.axle(role)
        if axle.type_code != "double_wishbone":
            self._status.setText(tr("analysis.unsupported"))
            return
        try:
            if self._spring.isChecked() and self._spring_length.value() <= 0:
                raise ValueError(tr("analysis.spring_length_required"))
            low, high = self._damper_min.value(), self._damper_max.value()
            if self._damper.isChecked() and ((low == 0) != (high == 0)):
                raise ValueError(tr("analysis.damper_limits_required"))
            damper_limits = StrokeLimits(low, high) if self._damper.isChecked() and low and high else None
            characteristic = None
            velocity = 0.0
            if self._damping.isChecked():
                velocity = self._explicit_number(self._velocity, -10000, 10000)
                compression = self._explicit_number(self._compression, 0, 10000)
                rebound = self._explicit_number(self._rebound, 0, 10000)
                characteristic = LinearDamperCharacteristic(compression, rebound)
            travels = travel_grid(self._from.value(), self._to.value(), max_spacing_mm=self._step.value())
            if len(travels) > 401:
                raise ValueError(tr("analysis.too_many_points"))
            side: Literal["left", "right"] = "left" if self._side.currentData() == "left" else "right"
            result = analyze_corner(
                axle, self.controller.project.vehicle, travels, side=side,
                spring_mount="lower_arm" if self._spring.isChecked() else None,
                static_spring_length_mm=self._spring_length.value() if self._spring.isChecked() else None,
                coil_bind_length_mm=(self._coil_bind.value() or None) if self._spring.isChecked() else None,
                damper_mount="lower_arm" if self._damper.isChecked() else None,
                damper_limits=damper_limits,
                max_step_mm=1.0,
            )
        except (ValueError, ArithmeticError) as error:
            LOG.warning("Расчёт хода не выполнен: %s", error)
            self._status.setText(tr("analysis.error", reason=str(error)))
            return
        # Отдельная подготовка проекции: сбой показа не подменяет результаты таблицы.
        model = DoubleWishbone(axle, side)
        frames: list[PoseView | None] = []
        for sample in result.samples:
            try:
                frame = pose_view(model, sample.pose, axle, spring=self._spring.isChecked(),
                                  damper=self._damper.isChecked()) if sample is not None else None
            except (ValueError, KeyError, ArithmeticError):
                frame = None
            frames.append(frame)
        radius, width = axle.wheel.r_dynamic_mm, axle.wheel.width_mm
        if not all(isfinite(value) and 0 < value < 100000 for value in (radius, width)):
            frames = [None] * len(frames)
        self._frames = frames
        self._playback_reasons = []
        for frame, sample in zip(frames, result.samples, strict=True):
            reason = None
            if frame is None or sample is None:
                reason = tr("playback.missing")
            elif sample.spring is not None and (sample.spring.error is not None or
                                                  (sample.spring.state is not None and sample.spring.state.status == "coil_bind")):
                reason = tr("playback.spring_conflict")
            elif sample.damper is not None and sample.damper.has_detected_conflict:
                reason = tr("playback.damper_conflict")
            self._playback_reasons.append(reason)
        self._cambers = [sample.geometry.camber_deg if sample is not None else 0 for sample in result.samples]
        self._preview.configure([frame for frame in frames if frame is not None], radius, width)
        self._table.setRowCount(len(travels))
        failures = 0
        for row, (point, sample) in enumerate(zip(result.sweep.points, result.samples, strict=True)):
            values = [f"{point.travel_mm:+.2f}", "—", "—", "—", "—", "—", "—", "—", "", "—", "—", "—"]
            if sample is None:
                failures += 1
                values[8] = str(point.error) if point.error is not None else tr("analysis.no_result")
            else:
                values[1] = f"{sample.geometry.camber_deg:.3f}"
                values[2] = f"{sample.geometry.toe_deg:.3f}"
                statuses: list[str] = []
                if sample.spring is not None:
                    spring = sample.spring
                    if spring.state is not None:
                        values[3] = f"{spring.state.length_mm:.2f}"
                        values[4] = f"{spring.state.compression_mm:.2f}"
                        if spring.state.force_n is not None:
                            values[5] = f"{spring.state.force_n:.1f}"
                        statuses.append(tr(f"analysis.spring_status.{spring.state.status}"))
                    if spring.error:
                        statuses.append(spring.error)
                if sample.damper is not None:
                    damper = sample.damper
                    values[6] = f"{damper.length_mm:.2f}"
                    if damper.motion_ratio is not None:
                        values[7] = f"{damper.motion_ratio:.3f}"
                    statuses.append(damper.error or tr(f"analysis.damper_status.{damper.stroke.status}" if damper.stroke else "analysis.damper_status.unknown"))
                    if characteristic is not None:
                        try:
                            dynamics = evaluate_linear_damping(damper, characteristic, velocity)
                            values[9] = f"{dynamics.compression_velocity_mm_s:+.2f}"
                            values[10] = f"{dynamics.wheel_force_n:+.1f}"
                            values[11] = f"{dynamics.dissipated_power_w:.2f}"
                        except ValueError as error:
                            statuses.append(tr("analysis.damping_unavailable", reason=str(error)))
                values[8] = "; ".join(statuses) or tr("analysis.geometry_only")
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self._table.setItem(row, column, item)
        if failures:
            first_error = next((point.error for point in result.sweep.points if point.error is not None), None)
            LOG.warning("Расчёт хода: нерешённых строк %d; первый отказ: %s", failures, first_error or "не указан")
        self._status.setText(tr("analysis.complete", count=len(travels), failures=failures))
        self._export_button.setEnabled(bool(travels))
        if travels:
            self._playback.set_count(len(travels))
            self._slider.setRange(0, len(travels) - 1)
            self._slider.setEnabled(True)
            self._previous.setEnabled(True)
            self._next.setEnabled(True)
            index = min(range(len(travels)), key=lambda i: abs(travels[i]))
            self._table.setCurrentCell(index, 0)
            self._show_row(index)

    def _show_row(self, row: int, *_args: object) -> None:
        if not 0 <= row < len(self._frames):
            self._playback.observe_row(row)
            return
        self._playback.observe_row(row)
        self._slider.blockSignals(True)
        self._slider.setValue(row)
        self._slider.blockSignals(False)
        frame = self._frames[row]
        if frame is None:
            # Сохраняем общий масштаб для возможного выбора следующей строки.
            self._preview.frame = None
            self._preview.message = tr("analysis.preview_no_pose")
            self._preview.update()
            self._preview_status.setText(tr("analysis.preview_no_pose"))
            return
        self._preview.show_frame(frame, self._cambers[row], 1 if self._side.currentData() == "left" else -1)
        item = self._table.item(row, 8)
        state = item.text() if item is not None else ""
        self._preview_status.setText(tr("analysis.preview_warning", state=state))

    def _report_parameters(self) -> list[tuple[str, str]]:
        axle = self.controller.project.axle(str(self._role.currentData()))
        unknown, disabled = tr("export.unknown"), tr("export.not_enabled")
        def optional(enabled: bool, value: float) -> str:
            return (str(value) if value else unknown) if enabled else disabled
        params = [
            (tr("analysis.role"), self._role.currentText()), (tr("export.axle_type"), tr(axle.spec.name_key)),
            (tr("analysis.side"), self._side.currentText()),
            (tr("analysis.from"), str(self._from.value())), (tr("analysis.to"), str(self._to.value())),
            (tr("analysis.step"), str(self._step.value())),
            (tr("analysis.spring_enable"), tr("export.yes") if self._spring.isChecked() else tr("export.no")),
            (tr("analysis.spring_length"), optional(self._spring.isChecked(), self._spring_length.value())),
            (tr("analysis.coil_bind"), optional(self._spring.isChecked(), self._coil_bind.value())),
            (tr("analysis.damper_enable"), tr("export.yes") if self._damper.isChecked() else tr("export.no")),
            (tr("analysis.damper_min"), optional(self._damper.isChecked(), self._damper_min.value())),
            (tr("analysis.damper_max"), optional(self._damper.isChecked(), self._damper_max.value())),
            (tr("analysis.damping_enable"), tr("export.yes") if self._damping.isChecked() else tr("export.no")),
        ]
        for label, field in (("velocity", self._velocity), ("compression", self._compression), ("rebound", self._rebound)):
            params.append((tr(f"analysis.{label}"), field.text() if self._damping.isChecked() else disabled))
        return params

    def _export(self) -> None:
        self._playback.stop(tr("playback.paused"))
        try:
            report = make_table_report(self.controller, self._table, tr("analysis.title"), self._report_parameters())
        except (ValueError, UnicodeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
            return
        save_table_dialog(self, report)

    def _playback_problem(self, row: int) -> str | None:
        return self._playback_reasons[row] if 0 <= row < len(self._playback_reasons) else tr("playback.missing")

    @staticmethod
    def _explicit_number(field: QLineEdit, minimum: float, maximum: float) -> float:
        try:
            value = float(field.text().strip().replace(",", "."))
        except ValueError as error:
            raise ValueError(tr("analysis.damping_input_required")) from error
        if not isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(tr("analysis.damping_input_required"))
        return value
