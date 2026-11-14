"""Явный экспериментальный поиск условного баланса одной стороны."""
from __future__ import annotations

import json
import logging
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.equilibrium import EquilibriumPath, EquilibriumPathError, EquilibriumResult, SpringEquilibrium
from ..core.stroke import StrokeLimits
from ..export.csv_report import CSVReport
from ..export.equilibrium_path import PATH_COLUMNS
from ..i18n import tr
from .controller import AppController
from .equilibrium_path_dialog import EquilibriumPathDialog
from .table_export import make_report, save_table_dialog

LOG = logging.getLogger(__name__)

# Порядок и подписи для CSV; значения берутся из того же снимка, что и текст окна.
_RESULT_FIELDS = ("lower", "upper", "lower_residual", "upper_residual", "travel", "length", "spring_force",
                  "ratio", "support", "residual", "samples", "step", "bind", "damper")


class EquilibriumDialog(QDialog):
    """Отдельное исследование без записи входов и результатов в проект."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(tr("equilibrium_ui.title"))
        self.resize(860, 650)
        self._role = QComboBox(self)
        self._side = QComboBox(self)
        for role in ("front", "rear"):
            self._role.addItem(tr(f"tree.{role}"), role)
        for side in ("left", "right"):
            self._side.addItem(tr(f"hp.side.{side}"), side)
        self._from = self._number(-100, 100, -30)
        self._to = self._number(-100, 100, 30)
        self._load = self._number(0, 100000, 0)
        self._length = self._number(0, 2000, 0)
        self._bind = self._number(0, 2000, 0)
        self._damper = QCheckBox(tr("equilibrium_ui.damper"), self)
        self._damper_min = self._number(0, 2000, 0)
        self._damper_max = self._number(0, 2000, 0)

        left = QFormLayout()
        right = QFormLayout()
        for key, widget in (("role", self._role), ("side", self._side), ("from", self._from),
                            ("to", self._to), ("load", self._load)):
            left.addRow(tr(f"equilibrium_ui.{key}"), widget)
        for key, widget in (("length", self._length), ("bind", self._bind)):
            right.addRow(tr(f"equilibrium_ui.{key}"), widget)
        right.addRow(self._damper)
        right.addRow(tr("equilibrium_ui.damper_min"), self._damper_min)
        right.addRow(tr("equilibrium_ui.damper_max"), self._damper_max)
        fields = QHBoxLayout()
        fields.addLayout(left)
        fields.addLayout(right)
        notice = QLabel(tr("equilibrium_ui.notice"), self)
        notice.setWordWrap(True)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._output = QLabel(self)
        self._output.setWordWrap(True)
        self._output.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._result: EquilibriumResult | None = None
        self._path: EquilibriumPath | None = None
        self._path_dialog: EquilibriumPathDialog | None = None
        self._display_values: dict[str, str] | None = None
        self._run = QPushButton(tr("equilibrium_ui.run"), self)
        self._run.clicked.connect(self._calculate)
        self._export_button = QPushButton(tr("equilibrium_ui.export"), self)
        self._export_button.clicked.connect(self._export)
        self._path_button = QPushButton(tr("equilibrium_path.button"), self)
        self._path_button.clicked.connect(self._show_path)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.button(QDialogButtonBox.StandardButton.Close).setText(tr("analysis.close"))
        close.rejected.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self._run)
        buttons.addWidget(self._export_button)
        buttons.addWidget(self._path_button)
        buttons.addStretch()
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addLayout(fields)
        layout.addWidget(self._status)
        layout.addWidget(self._output)
        layout.addStretch()
        layout.addLayout(buttons)
        for combo in (self._role, self._side):
            combo.currentIndexChanged.connect(self._invalidate)
        for number in (self._from, self._to, self._load, self._length, self._bind,
                       self._damper_min, self._damper_max):
            number.valueChanged.connect(self._invalidate)
        self._damper.toggled.connect(self._invalidate)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._invalidate)
        self._invalidate()

    def _number(self, minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox(self)
        box.setDecimals(1)
        box.setRange(minimum, maximum)
        box.setValue(value)
        return box

    def _invalidate(self, *_args: object) -> None:
        if self._path_dialog is not None:
            self._path_dialog.reject()
        self._path = None
        self._path_button.setEnabled(False)
        self._result = None
        self._display_values = None
        self._export_button.setEnabled(False)
        self._output.clear()
        self._damper_min.setEnabled(self._damper.isChecked())
        self._damper_max.setEnabled(self._damper.isChecked())
        supported = self.controller.project.axle(str(self._role.currentData())).type_code == "double_wishbone"
        self._run.setEnabled(supported)
        self._status.setText(tr("equilibrium_ui.ready" if supported else "analysis.unsupported"))

    def _calculate(self) -> None:
        if self._path_dialog is not None:
            self._path_dialog.reject()
        self._path = None
        self._path_button.setEnabled(False)
        self._result = None
        self._display_values = None
        self._export_button.setEnabled(False)
        self._output.clear()
        axle = self.controller.project.axle(str(self._role.currentData()))
        if axle.type_code != "double_wishbone":
            self._status.setText(tr("analysis.unsupported"))
            return
        try:
            if self._load.value() <= 0 or self._length.value() <= 0:
                raise ValueError(tr("equilibrium_ui.required"))
            limits = None
            if self._damper.isChecked():
                if self._damper_min.value() <= 0 or self._damper_max.value() <= 0:
                    raise ValueError(tr("equilibrium_ui.damper_required"))
                limits = StrokeLimits(self._damper_min.value(), self._damper_max.value())
            side: Literal["left", "right"] = "left" if self._side.currentData() == "left" else "right"
            problem = SpringEquilibrium(
                axle, self._length.value(), side=side, coil_bind_length_mm=self._bind.value() or None,
                damper_mount="lower_arm" if self._damper.isChecked() else None, damper_limits=limits,
                max_step_mm=1.0,
            )
            result = problem.find(self._load.value(), self._from.value(), self._to.value(),
                                  travel_tolerance_mm=0.1, path_step_mm=1.0)
        except EquilibriumPathError as error:
            self._path = error.path
            self._path_button.setEnabled(True)
            failure = error.path.failure
            assert failure is not None
            LOG.warning("Проверка пути баланса прервана: точка %.3f мм, отказ %.3f мм: %s",
                        failure.requested_travel_mm, failure.failure_travel_mm, failure.reason)
            self._status.setText(tr("equilibrium_ui.path_error", requested=f"{failure.requested_travel_mm:.3f}",
                                    failure=f"{failure.failure_travel_mm:.3f}", reason=failure.reason))
            return
        except (ValueError, ArithmeticError) as error:
            LOG.warning("Поиск баланса не выполнен: %s", error)
            self._status.setText(tr("equilibrium_ui.error", reason=str(error)))
            return
        self._result = result
        point = result.estimate
        assert result.path is not None
        self._path = result.path
        self._path_button.setEnabled(True)
        self._status.setText(tr("equilibrium_ui.success"))
        self._display_values = {
            "lower": f"{result.lower.travel_mm:.4f}", "upper": f"{result.upper.travel_mm:.4f}",
            "lower_residual": f"{result.lower.residual_n:+.4f}", "upper_residual": f"{result.upper.residual_n:+.4f}",
            "travel": f"{point.travel_mm:.4f}", "length": f"{point.spring.length_mm:.4f}",
            "spring_force": f"{point.spring.force_n:.4f}", "ratio": f"{point.motion_ratio:.6f}",
            "support": f"{point.wheel_support_n:.4f}", "residual": f"{point.residual_n:+.4f}",
            "samples": str(len(result.path.samples)), "step": f"{result.path.actual_step_mm:.4f}",
            "bind": tr("equilibrium_ui.checked" if self._bind.value() else "equilibrium_ui.unchecked"),
            "damper": tr("equilibrium_ui.checked" if self._damper.isChecked() else "equilibrium_ui.unchecked"),
        }
        self._output.setText(tr("equilibrium_ui.result", **self._display_values))
        self._export_button.setEnabled(True)

    def _show_path(self) -> None:
        if self._path is None:
            return
        path = self._path
        dialog = EquilibriumPathDialog(path, self, report_factory=lambda table: self._path_report(path, table))
        self._path_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._path_dialog = None
            dialog.deleteLater()

    def _path_report(self, path: EquilibriumPath, table: QTableWidget) -> CSVReport:
        """Снимок таблицы и результата проверки с явным описанием отказа."""
        if self._path is not path or table.rowCount() != len(path.samples) or table.columnCount() != len(PATH_COLUMNS):
            raise ValueError(tr("equilibrium_path.stale"))
        if ((path.failure is None and (self._result is None or self._result.path is not path))
                or (path.failure is not None and self._result is not None)):
            raise ValueError(tr("equilibrium_path.stale"))
        failure = path.failure
        params = [
            *self._report_parameters(),
            (tr("equilibrium_path.report_status"), tr("equilibrium_path.report_failed" if failure else "equilibrium_path.report_passed")),
            (tr("equilibrium_path.report_target"), f"{path.target_travel_mm:.4f}"),
            (tr("equilibrium_path.report_requested_step"), f"{path.requested_step_mm:.4f}"),
            (tr("equilibrium_path.report_actual_step"), f"{path.actual_step_mm:.4f}"),
            (tr("equilibrium_path.report_count"), str(len(path.samples))),
            (tr("equilibrium_path.report_failure_type"), tr(f"equilibrium_path.failure.{failure.kind}") if failure else "—"),
            (tr("equilibrium_path.report_failure_requested"), f"{failure.requested_travel_mm:.4f}" if failure else "—"),
            (tr("equilibrium_path.report_failure_actual"), f"{failure.failure_travel_mm:.4f}" if failure else "—"),
            (tr("equilibrium_path.report_failure_reason"), failure.reason if failure else "—"),
            (tr("equilibrium_path.report_limits"), tr("equilibrium_path.report_warning")),
        ]
        def item_text(row: int, column: int) -> str:
            item = table.item(row, column)
            if item is None:
                raise ValueError(tr("equilibrium_path.stale"))
            return item.text()

        headers = [table.horizontalHeaderItem(i) for i in range(table.columnCount())]
        if any(item is None for item in headers):
            raise ValueError(tr("equilibrium_path.stale"))
        columns = tuple(item.text() for item in headers if item is not None)
        rows = tuple(tuple(item_text(row, col) for col in range(table.columnCount()))
                     for row in range(table.rowCount()))
        return make_report(self.controller, tr("equilibrium_path.title"), params, columns, rows,
                           precision_text=tr("equilibrium_path.report_precision"),
                           allow_empty_rows=failure is not None and not path.samples)

    def _report_parameters(self) -> list[tuple[str, str]]:
        axle = self.controller.project.axle(str(self._role.currentData()))
        disabled, unknown = tr("export.not_enabled"), tr("export.unknown")
        return [
            (tr("equilibrium_ui.role"), self._role.currentText()),
            (tr("export.axle_type"), tr(axle.spec.name_key)),
            (tr("equilibrium_ui.side"), self._side.currentText()),
            (tr("equilibrium_ui.from"), str(self._from.value())),
            (tr("equilibrium_ui.to"), str(self._to.value())),
            (tr("equilibrium_ui.load"), str(self._load.value())),
            (tr("equilibrium_ui.length"), str(self._length.value())),
            (tr("equilibrium_ui.bind"), str(self._bind.value()) if self._bind.value() else unknown),
            (tr("equilibrium_ui.damper"), tr("export.yes") if self._damper.isChecked() else tr("export.no")),
            (tr("equilibrium_ui.damper_min"), str(self._damper_min.value()) if self._damper.isChecked() else disabled),
            (tr("equilibrium_ui.damper_max"), str(self._damper_max.value()) if self._damper.isChecked() else disabled),
            (tr("equilibrium_ui.spring_metadata"), json.dumps(axle.spring.to_dict(), ensure_ascii=False,
                                                               sort_keys=True, allow_nan=False)),
            (tr("equilibrium_ui.search_metadata"), tr("equilibrium_ui.search_settings")),
            (tr("equilibrium_ui.model_metadata"), tr("equilibrium_ui.notice")),
        ]

    def _export(self) -> None:
        if self._result is None or self._display_values is None:
            return
        try:
            rows = tuple((tr(f"equilibrium_ui.field.{key}"), self._display_values[key]) for key in _RESULT_FIELDS)
            report = make_report(self.controller, tr("equilibrium_ui.title"), self._report_parameters(),
                                 (tr("equilibrium_ui.field_name"), tr("equilibrium_ui.field_value")), rows,
                                 precision_text=tr("equilibrium_ui.export_precision"))
        except (ValueError, UnicodeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
            return
        save_table_dialog(self, report)
