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
from ..core.sweep_plot import PATH_PLOT_METRICS, PlotPoint, equilibrium_path_plot_points
from ..export.csv_report import CSVReport
from ..export.equilibrium_path import PATH_COLUMNS, format_path_sample
from ..i18n import tr
from .canvas.sweep_plot import SweepPlot
from .table_export import save_table_dialog


class EquilibriumPathDialog(QDialog):
    """Только пройденные точки и отдельно первый отказ, без повторного расчёта."""

    def __init__(self, path: EquilibriumPath, parent: QWidget | None = None, *,
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
        self._table = QTableWidget(len(path.samples), len(PATH_COLUMNS), self)
        self._table.setHorizontalHeaderLabels([tr(f"equilibrium_path.column.{key}") for key in PATH_COLUMNS])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        for index, sample in enumerate(path.samples):
            for column, text in enumerate(format_path_sample(sample)):
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
        self._plot.rowSelected.connect(lambda row: self._table.setCurrentCell(row, 0))
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
        self._views = QTabWidget(self)
        self._views.addTab(self._table, tr("equilibrium_path.tab_table"))
        self._views.addTab(plot_container, tr("analysis.tab_plot"))
        self._plot.set_points(equilibrium_path_plot_points(path))
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
        layout.addWidget(self._views, 1)
        layout.addLayout(bottom)

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
