"""Фильтр сохранённых расчётных строк кандидата пружины."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.spring_candidate import SpringComparison
from ..export.csv_report import CSVReport
from ..i18n import tr
from .canvas.spring_candidate_plot import SpringCandidatePlot


class SpringCandidatePointsDialog(QDialog):
    """Только исходные строки без повторного расчёта и без фильтрации CSV."""

    rowSelected = Signal(int)

    def __init__(self, comparison: SpringComparison, report: CSVReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if len(report.rows) != len(comparison.points) or len(report.columns) != 8 or any(len(row) != 8 for row in report.rows):
            raise ValueError("Несогласованные результаты сравнения")
        self.comparison = comparison
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowTitle(tr("spring_candidate.details.title"))
        self.resize(1100, 600)
        notice = QLabel(tr("spring_candidate.details.notice"), self)
        notice.setWordWrap(True)
        self._filter = QComboBox(self)
        for key in ("all", "invalid", "coil_bind", "uncompressed", "reserve_short", "missing", "clear"):
            self._filter.addItem(tr(f"spring_candidate.details.filter.{key}"), key)
        self._count = QLabel(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(tr("spring_candidate.details.filter_label"), self))
        controls.addWidget(self._filter)
        controls.addWidget(self._count, 1)
        self._table = QTableWidget(len(report.rows), len(report.columns), self)
        self._table.setHorizontalHeaderLabels(report.columns)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # Показываем состояние рядом с ходом даже при узком окне, не меняя порядок CSV.
        self._table.horizontalHeader().moveSection(6, 2)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        for i, row in enumerate(report.rows):
            for j, raw in enumerate(row):
                displayed = f"{float(raw):.3f}" if j in (1, 2, 3, 4, 5) and raw != "—" else raw
                item = QTableWidgetItem(displayed)
                item.setToolTip(raw)
                self._table.setItem(i, j, item)
        self._choose = QPushButton(tr("spring_candidate.details.choose"), self)
        self._choose.setEnabled(False)
        self._choose.clicked.connect(self._choose_row)
        self._table.cellDoubleClicked.connect(self._choose_row)
        self._table.currentCellChanged.connect(self._update_choice)
        self._filter.currentIndexChanged.connect(self._apply_filter)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("analysis.close"))
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self._choose)
        bottom.addStretch()
        bottom.addWidget(buttons)
        layout = QVBoxLayout(self)
        table_page = QWidget(self)
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addLayout(controls)
        table_layout.addWidget(self._table, 1)
        self._plot = SpringCandidatePlot(comparison, self)
        self._plot.rowSelected.connect(self._select_plot_row)
        self._plot_selection = QLabel(tr("spring_candidate.plot.selection_empty"), self)
        self._plot_selection.setWordWrap(True)
        plot_notice = QLabel(tr("spring_candidate.plot.legend"), self)
        plot_notice.setWordWrap(True)
        lower = comparison.candidate.coil_bind_mm + comparison.candidate.coil_reserve_mm
        upper = comparison.candidate.free_mm - comparison.candidate.compression_reserve_mm
        if lower > upper:
            plot_notice.setText(plot_notice.text() + "\n" + tr("spring_candidate.plot.crossed"))
        elif lower == upper:
            plot_notice.setText(plot_notice.text() + "\n" + tr("spring_candidate.plot.touching"))
        graph_page = QWidget(self)
        graph_layout = QVBoxLayout(graph_page)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.addWidget(self._plot, 1)
        graph_layout.addWidget(self._plot_selection)
        graph_layout.addWidget(plot_notice)
        self._tabs = QTabWidget(self)
        self._tabs.addTab(table_page, tr("spring_candidate.plot.table_tab"))
        self._tabs.addTab(graph_page, tr("spring_candidate.plot.graph_tab"))
        layout.addWidget(notice)
        layout.addWidget(self._tabs, 1)
        layout.addLayout(bottom)
        self._apply_filter()

    def _apply_filter(self, *_args: object) -> None:
        key = self._filter.currentData()
        visible = 0
        self._table.clearSelection()
        self._table.setCurrentCell(-1, -1)
        for row, point in enumerate(self.comparison.points):
            show = key == "all" or point.status == key
            self._table.setRowHidden(row, not show)
            visible += int(show)
        self._choose.setEnabled(False)
        self._count.setText(tr("spring_candidate.details.count", visible=visible, total=len(self.comparison.points)))

    def _update_choice(self, row: int, *_args: object) -> None:
        self._choose.setEnabled(0 <= row < self._table.rowCount() and not self._table.isRowHidden(row))
        self._plot.set_row(row)
        if 0 <= row < len(self.comparison.points):
            point = self.comparison.points[row]
            length = f"{point.length_mm:.3f}" if point.length_mm is not None else "—"
            self._plot_selection.setText(tr("spring_candidate.plot.selection", row=row + 1,
                                             travel=f"{point.travel_mm:+.3f}", length=length,
                                             status=tr(f"spring_candidate.report.status.{point.status}")))
        else:
            self._plot_selection.setText(tr("spring_candidate.plot.selection_empty"))

    def _select_plot_row(self, row: int) -> None:
        if 0 <= row < self._table.rowCount():
            if self._table.isRowHidden(row):
                self._filter.setCurrentIndex(self._filter.findData("all"))
            self._table.setCurrentCell(row, 0)

    def _choose_row(self, *_args: object) -> None:
        row = self._table.currentRow()
        if 0 <= row < self._table.rowCount() and not self._table.isRowHidden(row):
            self.accept()
            self.rowSelected.emit(row)
