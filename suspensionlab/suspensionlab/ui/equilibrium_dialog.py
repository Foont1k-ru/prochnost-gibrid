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
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.equilibrium import EquilibriumPath, EquilibriumPathError, EquilibriumResult, SpringEquilibrium
from ..core.mass_load import CornerKey, CornerMassLoad, FourWheelMassLoad, MassLoadEstimate, SymmetricMassLoad
from ..core.spring_candidate import SpringCandidate, candidate_geometry
from ..core.spring_characteristics import SpringCharacteristic
from ..core.stroke import StrokeLimits
from ..core.sweep_plot import PATH_PLOT_METRICS, PlotPoint, equilibrium_path_plot_points
from ..export.csv_report import CSVReport
from ..export.equilibrium_path import PATH_COLUMNS
from ..export.plot_report import plot_report_rows
from ..i18n import tr
from .controller import AppController
from .equilibrium_path_dialog import EquilibriumPathDialog
from .mass_load_dialog import MassLoadDialog
from .table_export import make_report, save_table_dialog

LOG = logging.getLogger(__name__)

# Порядок и подписи для CSV; значения берутся из того же снимка, что и текст окна.
_RESULT_FIELDS = ("lower", "upper", "lower_residual", "upper_residual", "travel", "length", "spring_force",
                  "ratio", "support", "residual", "samples", "step", "bind", "damper")
_CANDIDATE_RESULT_FIELDS = ("candidate_coil", "candidate_compression", "candidate_coil_condition",
                            "candidate_compression_condition", "candidate_status")


class EquilibriumDialog(QDialog):
    """Отдельное исследование без записи входов и результатов в проект."""

    def __init__(self, controller: AppController, parent: QWidget | None = None, *,
                 candidate: SpringCandidate | None = None, initial_role: str = "front", initial_side: str = "left") -> None:
        super().__init__(parent)
        if candidate is not None and (candidate.linear_rate_n_mm is None or initial_role not in ("front", "rear")
                                      or initial_side not in ("left", "right")):
            raise ValueError("Для баланса кандидата нужны жёсткость, ось и сторона")
        self.controller = controller
        self._candidate = candidate
        self._candidate_role, self._candidate_side = initial_role, initial_side
        self.setWindowTitle(tr("equilibrium_ui.title"))
        self.resize(860, 650)
        self._role = QComboBox(self)
        self._side = QComboBox(self)
        for role in ("front", "rear"):
            self._role.addItem(tr(f"tree.{role}"), role)
        for side in ("left", "right"):
            self._side.addItem(tr(f"hp.side.{side}"), side)
        if candidate is not None:
            self._role.setCurrentIndex(self._role.findData(initial_role))
            self._side.setCurrentIndex(self._side.findData(initial_side))
            self._role.setEnabled(False)
            self._side.setEnabled(False)
        self._from = self._number(-100, 100, -30)
        self._to = self._number(-100, 100, 30)
        self._load = self._number(0, 100000, 0)
        self._load_source: MassLoadEstimate | None = None
        self._mass_load_button = QPushButton(tr("equilibrium_ui.mass_load_button"), self)
        self._mass_load_button.clicked.connect(self._open_mass_load)
        self._load_source_label = QLabel(tr("equilibrium_ui.load_manual"), self)
        self._load_source_label.setWordWrap(True)
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
        left.addRow(self._mass_load_button)
        left.addRow(self._load_source_label)
        if candidate is None:
            for key, widget in (("length", self._length), ("bind", self._bind)):
                right.addRow(tr(f"equilibrium_ui.{key}"), widget)
        else:
            self._length.hide()
            self._bind.hide()
            self._candidate_length = QLineEdit(repr(candidate.installed_mm), self)
            self._candidate_bind = QLineEdit(repr(candidate.coil_bind_mm), self)
            self._candidate_length.setReadOnly(True)
            self._candidate_bind.setReadOnly(True)
            right.addRow(tr("equilibrium_ui.candidate_length"), self._candidate_length)
            right.addRow(tr("equilibrium_ui.bind"), self._candidate_bind)
        right.addRow(self._damper)
        right.addRow(tr("equilibrium_ui.damper_min"), self._damper_min)
        right.addRow(tr("equilibrium_ui.damper_max"), self._damper_max)
        fields = QHBoxLayout()
        fields.addLayout(left)
        fields.addLayout(right)
        if candidate is None:
            notice_text = tr("equilibrium_ui.notice")
        else:
            notice_text = tr("equilibrium_ui.candidate_notice", free=repr(candidate.free_mm),
                             rate=repr(candidate.linear_rate_n_mm), coil_reserve=repr(candidate.coil_reserve_mm),
                             compression_reserve=repr(candidate.compression_reserve_mm))
        notice = QLabel(notice_text, self)
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
            combo.currentIndexChanged.connect(self._context_changed)
        self._load.valueChanged.connect(self._load_changed)
        for number in (self._from, self._to, self._length, self._bind,
                       self._damper_min, self._damper_max):
            number.valueChanged.connect(self._invalidate)
        self._damper.toggled.connect(self._invalidate)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._context_changed)
        self._invalidate()

    def _load_changed(self, *_args: object) -> None:
        self._load_source = None
        self._load_source_label.setText(tr("equilibrium_ui.load_manual"))
        self._invalidate()

    def _context_changed(self, *_args: object) -> None:
        # Производная оценка относится к выбранной оси и проекту, не переносим её молча.
        if self._load_source is not None:
            self._load.setValue(0)
            self._load_source = None
            self._load_source_label.setText(tr("equilibrium_ui.load_manual"))
        self._invalidate()

    def _open_mass_load(self) -> None:
        role, side = self._role.currentData(), self._side.currentData()
        project = self.controller.project
        old_load = self._load.value()
        corners: dict[tuple[str, str], CornerKey] = {
            ("front", "left"): "front_left", ("front", "right"): "front_right",
            ("rear", "left"): "rear_left", ("rear", "right"): "rear_right",
        }
        corner = corners.get((str(role), str(side)))
        dialog = MassLoadDialog(self._role.currentText(), self._side.currentText(), self._load.maximum(), self,
                                corner_key=corner)
        if (dialog.exec() == QDialog.DialogCode.Accepted and dialog.estimate is not None
                and dialog.applied_load is not None and self.controller.project is project
                and self._role.currentData() == role and self._side.currentData() == side
                and self._load.value() == old_load):
            self._apply_mass_load(dialog.estimate, dialog.applied_load)
        dialog.deleteLater()

    def _apply_mass_load(self, estimate: MassLoadEstimate, load: float) -> None:
        self._load.setValue(load)
        self._load_source = estimate
        self._load_source_label.setText(tr("equilibrium_ui.load_estimated"))
        # Если поле уже содержало такое число, valueChanged не вызовет очистку старого результата.
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

    def _effective_length(self) -> float:
        return self._candidate.installed_mm if self._candidate is not None else self._length.value()

    def _effective_bind(self) -> float | None:
        return self._candidate.coil_bind_mm if self._candidate is not None else self._bind.value() or None

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
            if (self._candidate is not None and (self._role.currentData() != self._candidate_role
                                                or self._side.currentData() != self._candidate_side)):
                raise ValueError(tr("equilibrium_ui.candidate_context_error"))
            if self._load.value() <= 0 or self._effective_length() <= 0:
                raise ValueError(tr("equilibrium_ui.required"))
            limits = None
            if self._damper.isChecked():
                if self._damper_min.value() <= 0 or self._damper_max.value() <= 0:
                    raise ValueError(tr("equilibrium_ui.damper_required"))
                limits = StrokeLimits(self._damper_min.value(), self._damper_max.value())
            side: Literal["left", "right"] = "left" if self._side.currentData() == "left" else "right"
            characteristic = None
            if self._candidate is not None:
                assert self._candidate.linear_rate_n_mm is not None
                characteristic = SpringCharacteristic(self._candidate.free_mm, self._candidate.linear_rate_n_mm,
                                                      coil_bind_length_mm=self._candidate.coil_bind_mm)
            problem = SpringEquilibrium(
                axle, self._effective_length(), side=side, coil_bind_length_mm=self._effective_bind(),
                spring_characteristic=characteristic,
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
            "bind": tr("equilibrium_ui.checked" if self._effective_bind() is not None else "equilibrium_ui.unchecked"),
            "damper": tr("equilibrium_ui.checked" if self._damper.isChecked() else "equilibrium_ui.unchecked"),
        }
        output = tr("equilibrium_ui.result", **self._display_values)
        if self._candidate is not None:
            geometry = candidate_geometry(self._candidate, point.spring.length_mm)
            self._display_values.update({
                "candidate_coil": f"{geometry.coil_clearance_mm:.4f}",
                "candidate_compression": f"{geometry.compression_mm:.4f}",
                "candidate_coil_condition": tr("candidate_balance_reserve.ok" if geometry.coil_reserve_ok else "candidate_balance_reserve.short"),
                "candidate_compression_condition": tr("candidate_balance_reserve.ok" if geometry.compression_reserve_ok else "candidate_balance_reserve.short"),
                "candidate_status": tr(f"spring_candidate.report.status.{geometry.status}"),
            })
            output += "\n\n" + tr("candidate_balance_reserve.result", **self._display_values)
        self._output.setText(output)
        self._export_button.setEnabled(True)

    def _show_path(self) -> None:
        if self._path is None:
            return
        path = self._path
        dialog = EquilibriumPathDialog(
            path, self, report_factory=lambda table: self._path_report(path, table),
            graph_report_factory=lambda table, points, selected: self._path_graph_report(path, table, points, selected),
        )
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

    def _path_graph_report(self, path: EquilibriumPath, table: QTableWidget,
                           points: tuple[PlotPoint, ...], selected: str) -> CSVReport:
        """Все точки графика и полный статус пути, включая диагностический пустой результат."""
        table_report = self._path_report(path, table)  # Проверяет актуальность и наличие всех ячеек.
        if points != equilibrium_path_plot_points(path):
            raise ValueError(tr("equilibrium_path.stale"))
        status_columns = (PATH_COLUMNS.index("spring_status"), PATH_COLUMNS.index("damper_status"))
        context_labels = tuple(table_report.columns[i] for i in status_columns)
        context = tuple(tuple(row[i] for i in status_columns) for row in table_report.rows)
        columns, rows = plot_report_rows(
            points, tr("equilibrium_path.column.travel"),
            tuple(tr(f"equilibrium_path.column.{key}") for key in PATH_PLOT_METRICS),
            context_labels, context, allow_empty=path.failure is not None,
            conflict_label=tr("equilibrium_path.plot_conflict_column"),
        )
        metadata = tuple(
            (key, tr("export.plot_kind", kind=tr("equilibrium_path.title"))) if key == tr("export.kind") else
            (key, tr("export.plot_precision")) if key == tr("export.precision") else (key, value)
            for key, value in table_report.metadata
        )
        return CSVReport((*metadata, (tr("export.plot_selected"), selected)), columns, rows)

    def _report_parameters(self) -> list[tuple[str, str]]:
        axle = self.controller.project.axle(str(self._role.currentData()))
        disabled, unknown = tr("export.not_enabled"), tr("export.unknown")
        source = self._load_source
        if isinstance(source, SymmetricMassLoad):
            source_key = "load_source_mass"
            source_details = tr("equilibrium_ui.load_mass_values", mass=repr(source.total_mass_kg),
                                axle=repr(source.axle_percent), unsprung=repr(source.unsprung_corner_kg),
                                sprung=repr(source.corner_sprung_kg), reaction=repr(source.tire_reaction_n),
                                load=repr(source.sprung_load_n))
        elif isinstance(source, FourWheelMassLoad):
            source_key = f"load_source_four_{source.source_kind}"
            source_details = tr("equilibrium_ui.load_four_values", fl=repr(source.front_left_kg),
                                fr=repr(source.front_right_kg), rl=repr(source.rear_left_kg),
                                rr=repr(source.rear_right_kg), total=repr(source.total_kg),
                                front=repr(source.front_kg), rear=repr(source.rear_kg),
                                left=repr(source.left_kg), right=repr(source.right_kg),
                                front_pct=repr(source.front_percent), rear_pct=repr(source.rear_percent),
                                selected=tr(f"mass_load.corner.{source.selected}"),
                                unsprung=repr(source.unsprung_corner_kg), sprung=repr(source.corner_sprung_kg),
                                reaction=repr(source.tire_reaction_n), load=repr(source.sprung_load_n))
        elif isinstance(source, CornerMassLoad):
            source_key = f"load_source_{source.source_kind}"
            source_details = tr("equilibrium_ui.load_corner_values", wheel=repr(source.corner_total_kg),
                                unsprung=repr(source.unsprung_corner_kg), sprung=repr(source.corner_sprung_kg),
                                reaction=repr(source.tire_reaction_n), load=repr(source.sprung_load_n))
        else:
            source_key = "load_source_manual"
            source_details = "—"
        if self._candidate is None:
            spring_source = tr("equilibrium_ui.spring_source_project")
            spring_data = json.dumps(axle.spring.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False)
            spring_label = tr("equilibrium_ui.spring_metadata")
            limitations = tr("equilibrium_ui.notice")
        else:
            spring_source = tr("equilibrium_ui.spring_source_candidate")
            spring_data = json.dumps({"free_mm": self._candidate.free_mm, "installed_mm": self._candidate.installed_mm,
                                      "coil_bind_mm": self._candidate.coil_bind_mm,
                                      "linear_rate_n_mm": self._candidate.linear_rate_n_mm,
                                      "coil_reserve_mm": self._candidate.coil_reserve_mm,
                                      "compression_reserve_mm": self._candidate.compression_reserve_mm},
                                     ensure_ascii=False, sort_keys=True, allow_nan=False)
            spring_label = tr("equilibrium_ui.candidate_metadata")
            limitations = tr("equilibrium_ui.candidate_notice", free=repr(self._candidate.free_mm),
                             rate=repr(self._candidate.linear_rate_n_mm),
                             coil_reserve=repr(self._candidate.coil_reserve_mm),
                             compression_reserve=repr(self._candidate.compression_reserve_mm))
        return [
            (tr("equilibrium_ui.spring_source"), spring_source),
            (tr("equilibrium_ui.load_source"), tr(f"equilibrium_ui.{source_key}")),
            (tr("equilibrium_ui.load_mass_inputs"), source_details),
            (tr("equilibrium_ui.role"), self._role.currentText()),
            (tr("export.axle_type"), tr(axle.spec.name_key)),
            (tr("equilibrium_ui.side"), self._side.currentText()),
            (tr("equilibrium_ui.from"), str(self._from.value())),
            (tr("equilibrium_ui.to"), str(self._to.value())),
            (tr("equilibrium_ui.load"), str(self._load.value())),
            (tr("equilibrium_ui.candidate_length" if self._candidate is not None else "equilibrium_ui.length"),
             repr(self._effective_length())),
            (tr("equilibrium_ui.bind"), repr(self._effective_bind()) if self._effective_bind() is not None else unknown),
            (tr("equilibrium_ui.damper"), tr("export.yes") if self._damper.isChecked() else tr("export.no")),
            (tr("equilibrium_ui.damper_min"), str(self._damper_min.value()) if self._damper.isChecked() else disabled),
            (tr("equilibrium_ui.damper_max"), str(self._damper_max.value()) if self._damper.isChecked() else disabled),
            (spring_label, spring_data),
            (tr("equilibrium_ui.search_metadata"), tr("equilibrium_ui.search_settings")),
            (tr("equilibrium_ui.model_metadata"), limitations),
        ]

    def _export(self) -> None:
        if self._result is None or self._display_values is None:
            return
        try:
            fields = _RESULT_FIELDS + (_CANDIDATE_RESULT_FIELDS if self._candidate is not None else ())
            rows = tuple((tr(f"equilibrium_ui.field.{key}"), self._display_values[key]) for key in fields)
            report = make_report(self.controller, tr("equilibrium_ui.title"), self._report_parameters(),
                                 (tr("equilibrium_ui.field_name"), tr("equilibrium_ui.field_value")), rows,
                                 precision_text=tr("equilibrium_ui.export_precision"))
        except (ValueError, UnicodeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
            return
        save_table_dialog(self, report)
