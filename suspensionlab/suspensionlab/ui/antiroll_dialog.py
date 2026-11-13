"""Экспериментальная таблица двух стоек идеализированного стабилизатора."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.antiroll import AntiRollPoint, AntiRollScenario, AntiRollStudy
from ..core.sweep import travel_grid
from ..i18n import tr
from .analysis_dialog import AnalysisDialog
from .canvas.antiroll_preview import AntiRollPreview
from .controller import AppController


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

        fields = QHBoxLayout()
        sweep = QFormLayout()
        for key, control in (("role", self._role), ("mode", self._mode), ("from", self._from),
                             ("to", self._to), ("step", self._step)):
            sweep.addRow(tr(f"antiroll_ui.{key}"), control)
        params = QFormLayout()
        for key, edit in (("axis_x", self._axis_x), ("axis_z", self._axis_z), ("rate", self._rate)):
            params.addRow(tr(f"antiroll_ui.{key}"), edit)
        fields.addLayout(sweep)
        fields.addLayout(params)

        notice = QLabel(tr("antiroll_ui.notice"), self)
        notice.setWordWrap(True)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        columns = ("left_travel", "right_travel", "left_lower", "left_upper", "right_lower", "right_upper",
                   "left_angle", "right_angle", "twist", "torque", "left_force", "right_force", "state")
        self._table = QTableWidget(0, len(columns), self)
        self._table.setHorizontalHeaderLabels([tr(f"antiroll_ui.column.{key}") for key in columns])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._points: tuple[AntiRollPoint, ...] = ()
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("analysis.close"))
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self._run)
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
        for field in (self._from, self._to, self._step):
            field.valueChanged.connect(self._invalidate)
        for edit in (self._axis_x, self._axis_z, self._rate):
            edit.textChanged.connect(self._invalidate)
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
        self._points = ()
        self._preview.clear()
        self._preview_status.setText(tr("analysis.preview_empty"))
        self._slider.setEnabled(False)
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        self._table.setRowCount(0)

    def _invalidate(self, *_args: object) -> None:
        self._clear_results()
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
            grid = travel_grid(self._from.value(), self._to.value(), max_spacing_mm=self._step.value())
            if len(grid) > 401:
                raise ValueError(tr("analysis.too_many_points"))
            study = AntiRollStudy(axle, AntiRollScenario(x, z, rate))
            direction = 1 if self._mode.currentData() == "bounce" else -1
            result = study.sweep([(h, direction * h) for h in grid], max_step_mm=min(1, self._step.value()))
        except (ValueError, ArithmeticError) as error:
            self._status.setText(tr("analysis.error", reason=str(error)))
            return
        self._points = result.points
        self._preview.configure([point.state for point in result.points if point.state is not None], x, z)
        self._table.setRowCount(len(result.points))
        failures = 0
        for row, point in enumerate(result.points):
            values = [f"{point.left_travel_mm:+.2f}", f"{point.right_travel_mm:+.2f}"] + ["—"] * 10 + [""]
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
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self._table.setItem(row, column, item)
        self._status.setText(tr("analysis.complete", count=len(result.points), failures=failures))
        if result.points:
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
        if not 0 <= row < len(self._points):
            return
        self._slider.blockSignals(True)
        self._slider.setValue(row)
        self._slider.blockSignals(False)
        point = self._points[row]
        if point.state is None:
            self._preview.show_missing()
            self._preview_status.setText(tr("analysis.preview_no_pose"))
            return
        self._preview.show_frame(point.state)
        self._preview_status.setText(tr("antiroll_ui.preview_warning"))
