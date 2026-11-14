"""Экспериментальная таблица двух стоек идеализированного стабилизатора."""
from __future__ import annotations

import logging
from contextlib import suppress

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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.antiroll import AntiRollPoint, AntiRollScenario, AntiRollStudy
from ..core.combined_checks import ComponentCheckOptions, ComponentChecks, check_components
from ..core.double_wishbone import DoubleWishbone
from ..core.pose_view import PoseView, pose_view
from ..core.stroke import StrokeLimits
from ..core.sweep import travel_grid
from ..core.sweep_plot import ANTIROLL_METRICS, antiroll_plot_points
from ..i18n import tr
from .analysis_dialog import AnalysisDialog
from .canvas.antiroll_preview import AntiRollPreview
from .canvas.sweep_plot import SweepPlot
from .controller import AppController
from .table_export import make_table_report, save_table_dialog
from .widgets.playback import PlaybackControls

LOG = logging.getLogger(__name__)


class AntiRollDialog(QDialog):
    """Дискретное исследование стабилизатора с явно заданной осью и жёсткостью."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(tr("antiroll_ui.title"))
        self.resize(1200, 700)
        self._role = QComboBox(self)
        for role in ("front", "rear"):
            self._role.addItem(tr(f"tree.{role}"), role)
        self._mode = QComboBox(self)
        for mode in ("bounce", "opposed"):
            self._mode.addItem(tr(f"antiroll_ui.mode_{mode}"), mode)
        self._mode.setCurrentIndex(1)
        self._from = self._number(-100, 100, -30, 1)
        self._to = self._number(-100, 100, 30, 1)
        self._step = self._number(0.1, 20, 1, 0.1)
        self._axis_x = QLineEdit(self)
        self._axis_z = QLineEdit(self)
        self._rate = QLineEdit(self)
        for edit in (self._axis_x, self._axis_z, self._rate):
            edit.setPlaceholderText(tr("analysis.explicit_required"))
        self._show_spring = QCheckBox(tr("antiroll_ui.spring_overlay"), self)
        self._show_damper = QCheckBox(tr("antiroll_ui.damper_overlay"), self)
        self._spring_length = self._number(0, 2000, 0, 1)
        self._coil_bind = self._number(0, 2000, 0, 1)
        self._damper_min = self._number(0, 2000, 0, 1)
        self._damper_max = self._number(0, 2000, 0, 1)

        fields = QHBoxLayout()
        sweep = QFormLayout()
        for key, control in (("role", self._role), ("mode", self._mode), ("from", self._from),
                             ("to", self._to), ("step", self._step)):
            sweep.addRow(tr(f"antiroll_ui.{key}"), control)
        params = QFormLayout()
        for key, edit in (("axis_x", self._axis_x), ("axis_z", self._axis_z), ("rate", self._rate)):
            params.addRow(tr(f"antiroll_ui.{key}"), edit)
        params.addRow(self._show_spring)
        params.addRow(self._show_damper)
        checks = QFormLayout()
        for key, number in (("spring_length", self._spring_length), ("coil_bind", self._coil_bind),
                            ("damper_min", self._damper_min), ("damper_max", self._damper_max)):
            checks.addRow(tr(f"analysis.{key}"), number)
        fields.addLayout(sweep)
        fields.addLayout(params)
        fields.addLayout(checks)

        notice = QLabel(tr("antiroll_ui.notice"), self)
        notice.setWordWrap(True)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        columns = ("left_travel", "right_travel", "left_lower", "left_upper", "right_lower", "right_upper",
                   "left_angle", "right_angle", "twist", "torque", "left_force", "right_force", "state",
                   "spring_lengths", "spring_status", "damper_lengths", "damper_status")
        self._table = QTableWidget(0, len(columns), self)
        self._table.setHorizontalHeaderLabels([tr(f"antiroll_ui.column.{key}") for key in columns])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._points: tuple[AntiRollPoint, ...] = ()
        self._suspensions: list[tuple[PoseView, PoseView] | None] = []
        self._checks: list[tuple[ComponentChecks, ComponentChecks] | None] = []
        self._preview = AntiRollPreview(self)
        self._preview_status = QLabel(tr("analysis.preview_empty"), self)
        self._preview_status.setWordWrap(True)
        self._view = QComboBox(self)
        self._view.addItem(tr("antiroll_ui.view_front"), "front")
        self._view.addItem(tr("antiroll_ui.view_top"), "top")
        self._view.currentIndexChanged.connect(self._change_view)
        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setEnabled(False)
        self._previous = QPushButton(tr("analysis.previous"), self)
        self._next = QPushButton(tr("analysis.next"), self)
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        nav = QHBoxLayout()
        nav.addWidget(self._previous)
        nav.addWidget(self._slider, 1)
        nav.addWidget(self._next)
        preview_container = QWidget(self)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self._view)
        preview_layout.addWidget(self._preview, 1)
        preview_layout.addWidget(self._preview_status)
        preview_layout.addLayout(nav)
        self._playback = PlaybackControls(self._table.currentRow, lambda row: self._table.setCurrentCell(row, 0),
                                          self._playback_problem, self)
        preview_layout.addWidget(self._playback)
        self.finished.connect(lambda _result: self._playback.set_count(0))
        self._plot = SweepPlot(self, metrics=ANTIROLL_METRICS, label_prefix="antiroll_ui.column",
                               x_label="antiroll_ui.column.left_travel", empty_text="antiroll_ui.plot_empty")
        self._plot_metric = QComboBox(self)
        for key in ANTIROLL_METRICS:
            self._plot_metric.addItem(tr(f"antiroll_ui.column.{key}"), key)
        self._plot_metric.currentIndexChanged.connect(self._plot.set_metric)
        self._plot.rowSelected.connect(lambda row: self._table.setCurrentCell(row, 0))
        plot_selection = QLabel(tr("analysis.plot_no_selection"), self)
        plot_selection.setWordWrap(True)
        self._plot.selectionTextChanged.connect(plot_selection.setText)
        plot_notice = QLabel(tr("antiroll_ui.plot_notice"), self)
        plot_notice.setWordWrap(True)
        plot_container = QWidget(self)
        plot_layout = QVBoxLayout(plot_container)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addWidget(self._plot_metric)
        plot_layout.addWidget(self._plot, 1)
        plot_layout.addWidget(plot_selection)
        plot_layout.addWidget(plot_notice)
        self._view_tabs = QTabWidget(self)
        self._view_tabs.addTab(preview_container, tr("analysis.tab_pose"))
        self._view_tabs.addTab(plot_container, tr("analysis.tab_plot"))
        self._view_tabs.currentChanged.connect(self._playback.pause_for_view_change)
        self._split = QSplitter(Qt.Orientation.Horizontal, self)
        self._split.addWidget(self._table)
        self._split.addWidget(self._view_tabs)
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
        bottom = QHBoxLayout()
        bottom.addWidget(self._run)
        bottom.addWidget(self._export_button)
        bottom.addStretch()
        bottom.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addLayout(fields)
        layout.addWidget(self._status)
        layout.addWidget(self._split, 1)
        layout.addLayout(bottom)

        for combo in (self._role, self._mode):
            combo.currentIndexChanged.connect(self._invalidate)
        for field in (self._from, self._to, self._step, self._spring_length, self._coil_bind,
                      self._damper_min, self._damper_max):
            field.valueChanged.connect(self._invalidate)
        for edit in (self._axis_x, self._axis_z, self._rate):
            edit.textChanged.connect(self._invalidate)
        self._show_spring.toggled.connect(self._invalidate)
        self._show_damper.toggled.connect(self._invalidate)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._invalidate)
        self._invalidate()

    def _number(self, minimum: float, maximum: float, value: float, step: float) -> QDoubleSpinBox:
        field = QDoubleSpinBox(self)
        field.setRange(minimum, maximum)
        field.setDecimals(1)
        field.setSingleStep(step)
        field.setValue(value)
        return field

    def _clear_results(self) -> None:
        self._playback.set_count(0)
        self._export_button.setEnabled(False)
        self._points = ()
        self._suspensions = []
        self._checks = []
        self._plot.set_points(())
        self._preview.clear()
        self._preview_status.setText(tr("analysis.preview_empty"))
        self._slider.setEnabled(False)
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        self._table.setRowCount(0)

    def _invalidate(self, *_args: object) -> None:
        self._clear_results()
        self._spring_length.setEnabled(self._show_spring.isChecked())
        self._coil_bind.setEnabled(self._show_spring.isChecked())
        self._damper_min.setEnabled(self._show_damper.isChecked())
        self._damper_max.setEnabled(self._show_damper.isChecked())
        supported = self.controller.project.axle(str(self._role.currentData())).type_code == "double_wishbone"
        self._run.setEnabled(supported)
        self._status.setText(tr("analysis.ready" if supported else "analysis.unsupported"))

    @staticmethod
    def _vector(values: tuple[float, float, float]) -> str:
        return "; ".join(f"{value:.1f}" for value in values)

    def _calculate(self) -> None:
        self._clear_results()
        axle = self.controller.project.axle(str(self._role.currentData()))
        if axle.type_code != "double_wishbone":
            self._status.setText(tr("analysis.unsupported"))
            return
        try:
            try:
                x = AnalysisDialog._explicit_number(self._axis_x, -10000, 10000)
                z = AnalysisDialog._explicit_number(self._axis_z, -10000, 10000)
                rate = AnalysisDialog._explicit_number(self._rate, 0, 10000000)
            except ValueError as error:
                raise ValueError(tr("antiroll_ui.inputs_required")) from error
            spring_length = (self._spring_length.value() or None) if self._show_spring.isChecked() else None
            coil_bind = (self._coil_bind.value() or None) if self._show_spring.isChecked() else None
            if coil_bind is not None and (not axle.spring.free_len_mm > 0 or coil_bind >= axle.spring.free_len_mm):
                raise ValueError(tr("antiroll_ui.invalid_coil_bind"))
            low = self._damper_min.value() if self._show_damper.isChecked() else 0
            high = self._damper_max.value() if self._show_damper.isChecked() else 0
            if (low == 0) != (high == 0):
                raise ValueError(tr("analysis.damper_limits_required"))
            options = ComponentCheckOptions(spring_length, coil_bind, StrokeLimits(low, high) if low and high else None)
            grid = travel_grid(self._from.value(), self._to.value(), max_spacing_mm=self._step.value())
            if len(grid) > 401:
                raise ValueError(tr("analysis.too_many_points"))
            study = AntiRollStudy(axle, AntiRollScenario(x, z, rate))
            direction = 1 if self._mode.currentData() == "bounce" else -1
            result = study.sweep([(h, direction * h) for h in grid], max_step_mm=min(1, self._step.value()))
        except (ValueError, ArithmeticError) as error:
            LOG.warning("Расчёт стабилизатора не выполнен: %s", error)
            self._status.setText(tr("analysis.error", reason=str(error)))
            return
        self._points = result.points
        left_model, right_model = DoubleWishbone(axle, "left"), DoubleWishbone(axle, "right")
        static_pair: tuple[PoseView, PoseView] | None = None
        with suppress(ValueError, KeyError, ArithmeticError):
            static_pair = (pose_view(left_model, left_model.initial_pose(), axle, spring=self._show_spring.isChecked(),
                                     damper=self._show_damper.isChecked()),
                           pose_view(right_model, right_model.initial_pose(), axle, spring=self._show_spring.isChecked(),
                                     damper=self._show_damper.isChecked()))
        for point in result.points:
            pair = None
            if point.state is not None and point.left_pose is not None and point.right_pose is not None:
                with suppress(ValueError, KeyError, ArithmeticError):
                    pair = (pose_view(left_model, point.left_pose, axle, spring=self._show_spring.isChecked(),
                                      damper=self._show_damper.isChecked()),
                            pose_view(right_model, point.right_pose, axle, spring=self._show_spring.isChecked(),
                                      damper=self._show_damper.isChecked()))
            self._suspensions.append(pair)
            checks_pair = None
            if pair is not None and static_pair is not None:
                with suppress(ValueError, KeyError, ArithmeticError):
                    checks_pair = (check_components(pair[0], static_pair[0], options),
                                   check_components(pair[1], static_pair[1], options))
            self._checks.append(checks_pair)
        self._plot.set_points(antiroll_plot_points(result.points, self._checks))
        self._preview.configure([point.state for point in result.points if point.state is not None], x, z,
                                [view for pair in self._suspensions if pair is not None for view in pair])
        self._table.setRowCount(len(result.points))
        failures = 0
        for row, point in enumerate(result.points):
            values = [f"{point.left_travel_mm:+.2f}", f"{point.right_travel_mm:+.2f}"] + ["—"] * 10 + [""] + ["—"] * 4
            if point.state is None:
                failures += 1
                values[12] = point.error or tr("analysis.no_result")
            else:
                state = point.state
                values[2:6] = [self._vector(point) for point in (state.left.lower_mm, state.left.upper_mm,
                                                                  state.right.lower_mm, state.right.upper_mm)]
                values[6:12] = [f"{state.left.arm_angle_deg:+.2f}", f"{state.right.arm_angle_deg:+.2f}",
                                 f"{state.twist_deg:+.2f}", f"{state.torque_nm:+.2f}",
                                 f"{state.left.compression_force_n:+.1f}", f"{state.right.compression_force_n:+.1f}"]
                values[12] = tr("antiroll_ui.calculated")
                checks_pair = self._checks[row]
                if checks_pair is not None:
                    left, right = (self._component_text(check) for check in checks_pair)
                    values[13:17] = [f"{left[i]} / {right[i]}" for i in range(4)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self._table.setItem(row, column, item)
        if failures:
            first_error = next((point.error for point in result.points if point.error), None)
            LOG.warning("Расчёт стабилизатора: нерешённых строк %d; первый отказ: %s", failures, first_error or "не указан")
        self._status.setText(tr("analysis.complete", count=len(result.points), failures=failures))
        self._export_button.setEnabled(bool(result.points))
        if result.points:
            self._playback.set_count(len(result.points))
            self._slider.setRange(0, len(result.points) - 1)
            self._slider.setEnabled(True)
            self._previous.setEnabled(True)
            self._next.setEnabled(True)
            index = min(range(len(result.points)), key=lambda i: abs(result.points[i].left_travel_mm))
            self._table.setCurrentCell(index, 0)
            self._show_row(index)

    def _change_view(self, *_args: object) -> None:
        self._preview.set_mode("top" if self._view.currentData() == "top" else "front")

    def _show_row(self, row: int, *_args: object) -> None:
        self._plot.set_row(row)
        if not 0 <= row < len(self._points):
            self._playback.observe_row(row)
            return
        self._playback.observe_row(row)
        self._slider.blockSignals(True)
        self._slider.setValue(row)
        self._slider.blockSignals(False)
        point = self._points[row]
        if point.state is None:
            self._preview.show_missing()
            self._preview_status.setText(tr("analysis.preview_no_pose"))
            return
        suspension = self._suspensions[row]
        if suspension is None:
            self._preview.show_frame(point.state)
            self._preview_status.setText(tr("antiroll_ui.overlay_missing"))
        else:
            self._preview.show_frame(point.state, *suspension)
            checks = self._checks[row]
            if checks is None:
                self._preview_status.setText(tr("antiroll_ui.checks_missing"))
                return
            left, right = (self._component_text(check) for check in checks)
            self._preview_status.setText(tr("antiroll_ui.preview_warning") + "\n" + tr(
                "antiroll_ui.check_summary", spring_left=left[1], spring_right=right[1],
                damper_left=left[3], damper_right=right[3]))

    @staticmethod
    def _component_text(checks: ComponentChecks) -> tuple[str, str, str, str]:
        spring_length = damper_length = "—"
        spring_status = damper_status = tr("antiroll_ui.not_enabled")
        if checks.spring is not None:
            spring = checks.spring
            if spring.length_mm is not None:
                spring_length = f"{spring.length_mm:.2f}"
            spring_status = tr(f"antiroll_ui.spring_check.{spring.status}")
        if checks.damper is not None:
            damper = checks.damper
            if not damper.invalid:
                damper_length = f"{damper.length_mm:.2f}"
            if damper.invalid:
                damper_status = tr("antiroll_ui.damper_invalid")
            else:
                damper_status = tr(f"analysis.damper_status.{damper.stroke.status}" if damper.stroke else "analysis.damper_status.unknown")
        return spring_length, spring_status, damper_length, damper_status

    def _report_parameters(self) -> list[tuple[str, str]]:
        axle = self.controller.project.axle(str(self._role.currentData()))
        unknown, disabled = tr("export.unknown"), tr("export.not_enabled")
        def optional(enabled: bool, value: float) -> str:
            return (str(value) if value else unknown) if enabled else disabled
        return [
            (tr("antiroll_ui.role"), self._role.currentText()), (tr("export.axle_type"), tr(axle.spec.name_key)),
            (tr("antiroll_ui.mode"), self._mode.currentText()),
            (tr("antiroll_ui.from"), str(self._from.value())), (tr("antiroll_ui.to"), str(self._to.value())),
            (tr("antiroll_ui.step"), str(self._step.value())),
            (tr("antiroll_ui.axis_x"), self._axis_x.text()), (tr("antiroll_ui.axis_z"), self._axis_z.text()),
            (tr("antiroll_ui.rate"), self._rate.text()),
            (tr("antiroll_ui.spring_overlay"), tr("export.yes") if self._show_spring.isChecked() else tr("export.no")),
            (tr("analysis.spring_length"), optional(self._show_spring.isChecked(), self._spring_length.value())),
            (tr("analysis.coil_bind"), optional(self._show_spring.isChecked(), self._coil_bind.value())),
            (tr("antiroll_ui.damper_overlay"), tr("export.yes") if self._show_damper.isChecked() else tr("export.no")),
            (tr("analysis.damper_min"), optional(self._show_damper.isChecked(), self._damper_min.value())),
            (tr("analysis.damper_max"), optional(self._show_damper.isChecked(), self._damper_max.value())),
        ]

    def _export(self) -> None:
        self._playback.stop(tr("playback.paused"))
        try:
            report = make_table_report(self.controller, self._table, tr("antiroll_ui.title"), self._report_parameters())
        except (ValueError, UnicodeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
            return
        save_table_dialog(self, report)

    def _playback_problem(self, row: int) -> str | None:
        if not 0 <= row < len(self._points) or self._points[row].state is None or self._suspensions[row] is None:
            return tr("playback.missing")
        checks = self._checks[row]
        if checks is None:
            return tr("playback.missing")
        for check in checks:
            if check.spring is not None and check.spring.status in ("invalid", "coil_bind"):
                return tr("playback.spring_conflict")
            if check.damper is not None and (check.damper.invalid or
                    (check.damper.stroke is not None and check.damper.stroke.status != "inside")):
                return tr("playback.damper_conflict")
        return None
