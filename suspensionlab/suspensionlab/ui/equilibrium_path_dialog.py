"""Просмотр уже рассчитанных точек выборочной проверки пути."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.equilibrium import EquilibriumPath
from ..core.spring_candidate import SpringCandidate, candidate_geometry
from ..core.sweep_plot import PATH_PLOT_METRICS, PlotPoint, equilibrium_path_plot_points
from ..export.csv_report import CSVReport
from ..export.equilibrium_path import (
    CANDIDATE_PATH_COLUMNS,
    PATH_COLUMNS,
    candidate_path_comparison,
    candidate_path_diagnostic_row,
    candidate_path_summary,
    format_candidate_path_minima,
    format_candidate_path_sample,
    format_path_sample,
)
from ..i18n import tr
from .canvas.spring_candidate_plot import SpringCandidatePlot
from .canvas.sweep_plot import SweepPlot
from .table_export import save_table_dialog


class EquilibriumPathDialog(QDialog):
    """Только пройденные точки и отдельно первый отказ, без повторного расчёта."""

    def __init__(self, path: EquilibriumPath, parent: QWidget | None = None, *,
                 candidate: SpringCandidate | None = None,
                 report_factory: Callable[[QTableWidget], CSVReport] | None = None,
                 graph_report_factory: Callable[[QTableWidget, tuple[PlotPoint, ...], str], CSVReport] | None = None) -> None:
        super().__init__(parent)
        self._report_factory = report_factory
        self._graph_report_factory = graph_report_factory
        self.setWindowTitle(tr("equilibrium_path.title"))
        self.resize(1150, 600)
        notice = QLabel(tr("equilibrium_path.notice"), self)
        notice.setWordWrap(True)
        self._status = QLabel(self)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        if path.failure is None:
            self._status.setText(tr("equilibrium_path.completed", target=f"{path.target_travel_mm:.4f}",
                                    count=len(path.samples), step=f"{path.actual_step_mm:.4f}"))
        else:
            failure = path.failure
            self._status.setText(tr("equilibrium_path.failed", target=f"{path.target_travel_mm:.4f}",
                                    count=len(path.samples), requested=f"{failure.requested_travel_mm:.4f}",
                                    actual=f"{failure.failure_travel_mm:.4f}",
                                    kind=tr(f"equilibrium_path.failure.{failure.kind}"), reason=failure.reason))
        self._candidate_geometries = (tuple(candidate_geometry(candidate, sample.spring.length_mm) for sample in path.samples)
                                      if candidate is not None else ())
        columns = PATH_COLUMNS + (CANDIDATE_PATH_COLUMNS if candidate is not None else ())
        self._candidate_summary = QLabel(self)
        self._candidate_summary.setWordWrap(True)
        self._candidate_minima = QLabel(self)
        self._candidate_minima.setWordWrap(True)
        self._candidate_min_coil = QPushButton(tr("equilibrium_path.candidate_jump_coil"), self)
        self._candidate_min_compression = QPushButton(tr("equilibrium_path.candidate_jump_compression"), self)
        self._candidate_min_coil.setEnabled(False)
        self._candidate_min_compression.setEnabled(False)
        if candidate is not None:
            summary = candidate_path_summary(path, candidate)
            self._candidate_summary.setText(tr("equilibrium_path.candidate_summary", count=summary.total,
                                               coil=summary.coil_short, compression=summary.compression_short))
            self._candidate_minima.setText("\n".join(format_candidate_path_minima(summary, diagnostic_row=candidate_path_diagnostic_row(path))))
            if summary.minimum_coil is not None and summary.minimum_compression is not None:
                coil_row = summary.minimum_coil.row
                compression_row = summary.minimum_compression.row
                self._candidate_min_coil.setEnabled(True)
                self._candidate_min_compression.setEnabled(True)
                self._candidate_min_coil.clicked.connect(lambda: self._select_candidate_minimum(
                    coil_row, PATH_COLUMNS.index("coil_clearance")))
                self._candidate_min_compression.clicked.connect(lambda: self._select_candidate_minimum(
                    compression_row, len(PATH_COLUMNS) + CANDIDATE_PATH_COLUMNS.index("candidate_compression")))
        else:
            self._candidate_summary.hide()
            self._candidate_minima.hide()
            self._candidate_min_coil.hide()
            self._candidate_min_compression.hide()
        self._table = QTableWidget(len(path.samples), len(columns), self)
        self._table.setHorizontalHeaderLabels([tr(f"equilibrium_path.column.{key}") for key in columns])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        for index, sample in enumerate(path.samples):
            row = format_path_sample(sample)
            if candidate is not None:
                row += format_candidate_path_sample(sample, candidate)
            for column, text in enumerate(row):
                self._table.setItem(index, column, QTableWidgetItem(text))
        self._plot = SweepPlot(self, metrics=PATH_PLOT_METRICS, label_prefix="equilibrium_path.column",
                               x_label="equilibrium_path.column.travel", empty_text="equilibrium_path.plot_empty",
                               zero_reference_metrics=("residual",))
        self._plot_metric = QComboBox(self)
        for key in PATH_PLOT_METRICS:
            self._plot_metric.addItem(tr(f"equilibrium_path.column.{key}"), key)
        self._plot_metric.setCurrentIndex(PATH_PLOT_METRICS.index("residual"))
        self._plot.set_metric(self._plot_metric.currentIndex())
        self._plot_metric.currentIndexChanged.connect(self._plot.set_metric)
        self._plot.rowSelected.connect(self._select_path_row)
        self._table.currentCellChanged.connect(lambda row, *_args: self._plot.set_row(row))
        plot_selection = QLabel(tr("analysis.plot_no_selection"), self)
        plot_selection.setWordWrap(True)
        self._plot.selectionTextChanged.connect(plot_selection.setText)
        plot_notice = QLabel(tr("equilibrium_path.plot_notice"), self)
        plot_notice.setWordWrap(True)
        plot_container = QWidget(self)
        plot_layout = QVBoxLayout(plot_container)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addWidget(self._plot_metric)
        plot_layout.addWidget(self._plot, 1)
        plot_layout.addWidget(plot_selection)
        plot_layout.addWidget(plot_notice)
        self._plot_export_button = QPushButton(tr("export.plot_button"), self)
        self._plot_export_button.setEnabled(graph_report_factory is not None and (bool(path.samples) or path.failure is not None))
        self._plot_export_button.clicked.connect(self._export_graph)
        plot_layout.addWidget(self._plot_export_button)
        self._coil_filter = QComboBox(self)
        self._compression_filter = QComboBox(self)
        for combo in (self._coil_filter, self._compression_filter):
            for key in ("all", "ok", "short"):
                combo.addItem(tr(f"equilibrium_path.candidate_filter.{key}"), key)
        self._filter_count = QLabel(self)
        self._filter_count.setWordWrap(True)
        table_page = QWidget(self)
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)
        if candidate is not None:
            filter_row = QHBoxLayout()
            filter_row.addWidget(QLabel(tr("equilibrium_path.candidate_filter.coil"), self))
            filter_row.addWidget(self._coil_filter)
            filter_row.addWidget(QLabel(tr("equilibrium_path.candidate_filter.compression"), self))
            filter_row.addWidget(self._compression_filter)
            filter_row.addStretch(1)
            table_layout.addLayout(filter_row)
            table_layout.addWidget(self._filter_count)
            self._coil_filter.currentIndexChanged.connect(self._apply_candidate_filters)
            self._compression_filter.currentIndexChanged.connect(self._apply_candidate_filters)
        else:
            self._coil_filter.hide()
            self._compression_filter.hide()
            self._filter_count.hide()
        table_layout.addWidget(self._table, 1)
        self._views = QTabWidget(self)
        self._views.addTab(table_page, tr("equilibrium_path.tab_table"))
        self._views.addTab(plot_container, tr("analysis.tab_plot"))
        self._candidate_plot: SpringCandidatePlot | None = None
        self._candidate_plot_selection: QLabel | None = None
        self._candidate_plot_export: QPushButton | None = None
        if candidate is not None:
            comparison = candidate_path_comparison(path, candidate)
            diagnostic = candidate_path_diagnostic_row(path)
            self._candidate_plot = SpringCandidatePlot(
                comparison, self, diagnostic_rows=frozenset((diagnostic,)) if diagnostic is not None else frozenset())
            self._candidate_plot.rowSelected.connect(self._select_path_row)
            self._candidate_plot_selection = QLabel(tr("spring_candidate.plot.selection_empty"), self)
            self._candidate_plot_selection.setWordWrap(True)
            lower = candidate.coil_bind_mm + candidate.coil_reserve_mm
            upper = candidate.free_mm - candidate.compression_reserve_mm
            candidate_notice = QLabel(tr("equilibrium_path.candidate_plot_notice", coil=repr(candidate.coil_bind_mm),
                                         free=repr(candidate.free_mm), lower=repr(lower), upper=repr(upper)), self)
            candidate_notice.setWordWrap(True)
            if lower > upper:
                candidate_notice.setText(candidate_notice.text() + "\n" + tr("spring_candidate.plot.crossed"))
            elif lower == upper:
                candidate_notice.setText(candidate_notice.text() + "\n" + tr("spring_candidate.plot.touching"))
            self._candidate_plot_export = QPushButton(tr("export.plot_button"), self)
            self._candidate_plot_export.setEnabled(graph_report_factory is not None and (bool(path.samples) or path.failure is not None))
            self._candidate_plot_export.clicked.connect(self._export_candidate_graph)
            candidate_page = QWidget(self)
            candidate_layout = QVBoxLayout(candidate_page)
            candidate_layout.setContentsMargins(0, 0, 0, 0)
            candidate_layout.addWidget(self._candidate_plot, 1)
            candidate_layout.addWidget(self._candidate_plot_selection)
            candidate_layout.addWidget(candidate_notice)
            candidate_layout.addWidget(self._candidate_plot_export)
            self._views.addTab(candidate_page, tr("equilibrium_path.candidate_plot_tab"))
            self._table.currentCellChanged.connect(self._update_candidate_plot)
        self._plot.set_points(equilibrium_path_plot_points(path))
        if candidate is not None:
            self._apply_candidate_filters()
        if path.samples:
            self._table.setCurrentCell(0, 0)
            self._plot.set_row(0)
        self._export_button = QPushButton(tr("equilibrium_path.export"), self)
        self._export_button.setEnabled(report_factory is not None)
        self._export_button.clicked.connect(self._export)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("analysis.close"))
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self._export_button)
        bottom.addStretch()
        bottom.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addWidget(self._status)
        layout.addWidget(self._candidate_summary)
        layout.addWidget(self._candidate_minima)
        candidate_buttons = QHBoxLayout()
        candidate_buttons.addWidget(self._candidate_min_coil)
        candidate_buttons.addWidget(self._candidate_min_compression)
        candidate_buttons.addStretch()
        layout.addLayout(candidate_buttons)
        layout.addWidget(self._views, 1)
        layout.addLayout(bottom)

    @staticmethod
    def _matches_candidate_filter(key: str, condition_ok: bool) -> bool:
        return key == "all" or (key == "ok" and condition_ok) or (key == "short" and not condition_ok)

    def _apply_candidate_filters(self, *_args: object) -> None:
        coil, compression = self._coil_filter.currentData(), self._compression_filter.currentData()
        visible = [self._matches_candidate_filter(coil, geometry.coil_reserve_ok)
                   and self._matches_candidate_filter(compression, geometry.compression_reserve_ok)
                   for geometry in self._candidate_geometries]
        current = self._table.currentRow()
        if 0 <= current < len(visible) and not visible[current]:
            self._table.clearSelection()
            self._table.setCurrentCell(-1, -1)
        for row, show in enumerate(visible):
            self._table.setRowHidden(row, not show)
        self._filter_count.setText(tr("equilibrium_path.candidate_filter.count", visible=sum(visible), total=len(visible)))

    def _select_path_row(self, row: int, column: int = 0) -> None:
        if not 0 <= row < self._table.rowCount():
            return
        if self._candidate_geometries:
            geometry = self._candidate_geometries[row]
            for combo, condition in ((self._coil_filter, geometry.coil_reserve_ok),
                                     (self._compression_filter, geometry.compression_reserve_ok)):
                if not self._matches_candidate_filter(combo.currentData(), condition):
                    combo.blockSignals(True)
                    combo.setCurrentIndex(combo.findData("all"))
                    combo.blockSignals(False)
            self._apply_candidate_filters()
        self._table.setCurrentCell(row, column)

    def _update_candidate_plot(self, row: int, *_args: object) -> None:
        plot, label = self._candidate_plot, self._candidate_plot_selection
        if plot is None or label is None:
            return
        plot.set_row(row)
        if not 0 <= row < len(plot.comparison.points):
            label.setText(tr("spring_candidate.plot.selection_empty"))
            return
        point = plot.comparison.points[row]
        text = tr("spring_candidate.plot.selection", row=row + 1, travel=f"{point.travel_mm:+.4f}",
                  length=f"{point.length_mm:.4f}" if point.length_mm is not None else "—",
                  status=tr(f"spring_candidate.report.status.{point.status}"))
        if row in plot.diagnostic_rows:
            text += " " + tr("equilibrium_path.candidate_min_diagnostic")
        label.setText(text)

    def _export_candidate_graph(self) -> None:
        if self._graph_report_factory is None:
            return
        try:
            report = self._graph_report_factory(self._table, self._plot.points, tr("equilibrium_path.candidate_plot_selected"))
        except (ValueError, UnicodeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
            return
        save_table_dialog(self, report)

    def _select_candidate_minimum(self, row: int, column: int) -> None:
        self._views.setCurrentIndex(0)
        self._select_path_row(row, column)
        item = self._table.item(row, column)
        if item is not None:
            self._table.scrollToItem(item)

    def _export_graph(self) -> None:
        if self._graph_report_factory is None:
            return
        try:
            report = self._graph_report_factory(self._table, self._plot.points, self._plot_metric.currentText())
        except (ValueError, UnicodeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
            return
        save_table_dialog(self, report)

    def _export(self) -> None:
        if self._report_factory is None:
            return
        try:
            report = self._report_factory(self._table)
        except (ValueError, UnicodeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
            return
        save_table_dialog(self, report)
