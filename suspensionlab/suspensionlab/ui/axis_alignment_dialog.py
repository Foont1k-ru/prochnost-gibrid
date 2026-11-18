"""Просмотр и сравнение схематических опор без изменений проекта."""
from __future__ import annotations

from math import isfinite

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.axis_alignment import AxisAlignmentRow, AxisLimitCheck, AxisLimits, check_axis_limits, summarize_axis_maxima
from ..core.sweep_plot import PlotPoint
from ..export.axis_alignment import with_axis_limits
from ..export.csv_report import CSVReport
from ..i18n import tr
from .canvas.sweep_plot import SweepPlot
from .table_export import save_table_dialog

AXIS_METRICS = ("angle", "lower", "upper", "lower_pair", "upper_pair", "lower_axial", "upper_axial")


class AxisAlignmentDialog(QDialog):
    rowSelected = Signal(int)

    def __init__(self, rows: tuple[AxisAlignmentRow, ...], report: CSVReport, parent: QWidget | None = None, *,
                 source_conflicts: tuple[bool, ...]) -> None:
        super().__init__(parent)
        if (len(report.rows) != len(rows) or len(source_conflicts) != len(rows) or len(report.columns) != 11
                or any(len(row) != 11 for row in report.rows)):
            raise ValueError(tr("export.no_results"))
        self.setWindowTitle(tr("axis_alignment.title"))
        self.resize(1000, 650)
        self._rows = rows
        self._maxima = summarize_axis_maxima(rows)
        self._base_report = report
        self._report: CSVReport | None = None
        self._checks: tuple[AxisLimitCheck, ...] = ()
        self._table = QTableWidget(len(rows), 15, self)
        columns = (*report.columns, *(tr(f"axis_alignment.limits.column.{key}") for key in ("angle", "lower", "upper", "combined")))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        for row, (data, values) in enumerate(zip(rows, report.rows, strict=True)):
            result = data.result
            display = (values[0], f"{data.travel_mm:+.3f}",
                       f"{result.angle_deg:.4f}" if result else "—",
                       f"{result.lower_offset_mm:.4f}" if result else "—",
                       f"{result.upper_offset_mm:.4f}" if result else "—",
                       f"{result.lower_pair_distance_mm:.4f}" if result else "—",
                       f"{result.upper_pair_distance_mm:.4f}" if result else "—",
                       f"{result.lower_axial_mm:+.4f}" if result else "—",
                       f"{result.upper_axial_mm:+.4f}" if result else "—", values[9], values[10], "", "", "", "")
            for col, text in enumerate(display):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self._table.setItem(row, col, item)
        notice = QLabel(tr("axis_alignment.notice"), self)
        notice.setWordWrap(True)
        self._count = QLabel(self)
        self._count.setWordWrap(True)
        self._filter = QComboBox(self)
        for key in ("all", "exceeded", "within", "partial", "unchecked", "missing"):
            self._filter.addItem(tr(f"axis_alignment.limits.filter.{key}"), key)
        self._filter.currentIndexChanged.connect(self._apply_filter)
        self._visible_count = QLabel(self)
        self._visible_count.setWordWrap(True)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(tr("axis_alignment.limits.filter_label"), self))
        filter_row.addWidget(self._filter)
        filter_row.addStretch(1)
        table_container = QWidget(self)
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addLayout(filter_row)
        table_layout.addWidget(self._visible_count)
        table_layout.addWidget(self._table, 1)

        self._plot = SweepPlot(self, metrics=AXIS_METRICS, label_prefix="axis_alignment.column",
                               x_label="axis_alignment.column.travel", zero_reference_metrics=("lower_axial", "upper_axial"))
        points = []
        for data, conflict in zip(rows, source_conflicts, strict=True):
            result = data.result
            metric_values: tuple[float | None, ...] = ((result.angle_deg, result.lower_offset_mm, result.upper_offset_mm,
                       result.lower_pair_distance_mm, result.upper_pair_distance_mm, result.lower_axial_mm,
                       result.upper_axial_mm) if result else (None,) * 7)
            points.append(PlotPoint(data.travel_mm, metric_values, conflict))
        self._plot.set_points(tuple(points))
        self._metric = QComboBox(self)
        for key in AXIS_METRICS:
            self._metric.addItem(tr(f"axis_alignment.column.{key}"), key)
        self._metric.currentIndexChanged.connect(self._plot.set_metric)
        self._plot.rowSelected.connect(self._select_plot_row)
        self._plot_selection = QLabel(tr("analysis.plot_no_selection"), self)
        self._plot_selection.setWordWrap(True)
        self._plot.selectionTextChanged.connect(self._plot_selection.setText)
        plot_notice = QLabel(tr("axis_alignment.plot_notice"), self)
        plot_notice.setWordWrap(True)
        graph = QWidget(self)
        graph_layout = QVBoxLayout(graph)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.addWidget(self._metric)
        graph_layout.addWidget(self._plot, 1)
        graph_layout.addWidget(self._plot_selection)
        graph_layout.addWidget(plot_notice)

        self._limit_fields = {key: QLineEdit(self) for key in ("angle", "lower", "upper")}
        limits_form = QFormLayout()
        for key, field in self._limit_fields.items():
            field.setPlaceholderText(tr("axis_alignment.limits.placeholder"))
            limits_form.addRow(tr(f"axis_alignment.limits.field.{key}"), field)
            field.textChanged.connect(self._update_limits)
        self._limit_status = QLabel(self)
        self._limit_status.setWordWrap(True)
        limits_notice = QLabel(tr("axis_alignment.limits.notice"), self)
        limits_notice.setWordWrap(True)
        self._max_buttons: dict[str, QPushButton] = {}
        limits_content = QWidget(self)
        limits_layout = QVBoxLayout(limits_content)
        limits_layout.addWidget(limits_notice)
        limits_layout.addLayout(limits_form)
        limits_layout.addWidget(self._limit_status)
        limits_layout.addWidget(QLabel(tr("axis_alignment.maxima_title"), self))
        for key, extremum in (("angle", self._maxima.angle), ("lower", self._maxima.lower), ("upper", self._maxima.upper)):
            button = QPushButton(self)
            self._max_buttons[key] = button
            if extremum is not None:
                button.setText(tr(f"axis_alignment.maximum.{key}", value=f"{extremum.value:.4f}",
                                  travel=f"{extremum.travel_mm:+.3f}", row=extremum.row + 1))
                button.clicked.connect(lambda _checked=False, row=extremum.row: self._select_maximum(row))
            else:
                button.setText(tr(f"axis_alignment.maximum_empty.{key}"))
                button.setEnabled(False)
            limits_layout.addWidget(button)
        limits_layout.addStretch(1)
        limits_page = QScrollArea(self)
        limits_page.setWidgetResizable(True)
        limits_page.setWidget(limits_content)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(table_container, tr("axis_alignment.table_tab"))
        self._tabs.addTab(graph, tr("axis_alignment.plot_tab"))
        self._tabs.addTab(limits_page, tr("axis_alignment.limits.tab"))
        self._choose = QPushButton(tr("axis_alignment.choose"), self)
        self._choose.setEnabled(False)
        self._choose.clicked.connect(self._select)
        self._table.currentCellChanged.connect(self._current_changed)
        self._export = QPushButton(tr("axis_alignment.export"), self)
        self._export.clicked.connect(self._export_report)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.button(QDialogButtonBox.StandardButton.Close).setText(tr("analysis.close"))
        close.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self._choose)
        bottom.addWidget(self._export)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addWidget(self._count)
        layout.addWidget(self._tabs, 1)
        layout.addLayout(bottom)
        self._update_limits()
        if rows:
            self._table.setCurrentCell(0, 0)

    def _update_limits(self, *_args: object) -> None:
        def parse(key: str) -> float | None:
            text = self._limit_fields[key].text().strip()
            if not text:
                return None
            value = float(text.replace(",", "."))
            if not isfinite(value):
                raise ValueError
            return value
        try:
            limits = AxisLimits(parse("angle"), parse("lower"), parse("upper"))
        except (ValueError, OverflowError):
            self._checks = ()
            self._report = None
            self._export.setEnabled(False)
            self._filter.setEnabled(False)
            self._limit_status.setText(tr("axis_alignment.limits.invalid"))
            for row in range(len(self._rows)):
                for col in range(11, 15):
                    item = self._table.item(row, col)
                    if item is not None:
                        item.setText("—")
                        item.setToolTip("")
            self._filter.setCurrentIndex(0)
            self._apply_filter()
            return
        self._checks = tuple(check_axis_limits(row.result, limits) for row in self._rows)
        self._report = with_axis_limits(self._base_report, self._checks, limits, self._maxima)
        self._export.setEnabled(True)
        self._filter.setEnabled(True)
        for row, check in enumerate(self._checks):
            values = [tr(f"axis_alignment.limits.status.{v}") for v in (check.angle, check.lower, check.upper)]
            values.append(tr(f"axis_alignment.limits.combined.{check.combined}"))
            for col, text in enumerate(values, 11):
                item = self._table.item(row, col)
                if item is not None:
                    item.setText(text)
                    item.setToolTip(text)
        counts = {key: sum(check.combined == key for check in self._checks)
                  for key in ("within", "partial", "exceeded", "unchecked", "missing")}
        self._limit_status.setText(tr("axis_alignment.limits.counts", **counts))
        self._count.setText(tr("axis_alignment.count", available=sum(row.result is not None for row in self._rows),
                               total=len(self._rows)))
        self._apply_filter()

    def _apply_filter(self, *_args: object) -> None:
        selected = self._filter.currentData()
        visible = [selected == "all" or (bool(self._checks) and self._checks[i].combined == selected)
                   for i in range(len(self._rows))]
        current = self._table.currentRow()
        if 0 <= current < len(visible) and not visible[current]:
            self._table.clearSelection()
            self._table.setCurrentCell(-1, -1)
        for row, show in enumerate(visible):
            self._table.setRowHidden(row, not show)
        self._visible_count.setText(tr("axis_alignment.limits.visible", visible=sum(visible), total=len(visible)))

    def _current_changed(self, row: int, *_args: object) -> None:
        self._choose.setEnabled(0 <= row < len(self._rows) and not self._table.isRowHidden(row))
        self._plot.set_row(row)

    def _select_plot_row(self, row: int) -> None:
        if not 0 <= row < len(self._rows):
            return
        if self._table.isRowHidden(row):
            self._filter.setCurrentIndex(0)
        self._table.setCurrentCell(row, 0)

    def _select_maximum(self, row: int) -> None:
        self._select_plot_row(row)
        self._tabs.setCurrentIndex(0)

    def _export_report(self) -> None:
        if self._report is not None:
            save_table_dialog(self, self._report)

    def _select(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < self._table.rowCount() and not self._table.isRowHidden(row):
            self.rowSelected.emit(row)
            self.accept()
