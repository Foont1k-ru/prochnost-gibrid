"""Просмотр и фильтрация уже рассчитанных точек кандидата амортизатора."""
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

from ..core.damper_range import CandidateComparison
from ..i18n import tr
from .canvas.damper_candidate_plot import DamperCandidatePlot


class DamperCandidateDialog(QDialog):
    """Снимок результатов; фильтры не вычисляют новые точки и не меняют проект."""

    rowSelected = Signal(int)

    def __init__(self, comparison: CandidateComparison, columns: tuple[str, ...],
                 rows: tuple[tuple[str, ...], ...], context: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if len(rows) != len(comparison.points) or len(columns) != 8 or any(len(row) != 8 for row in rows):
            raise ValueError("Несогласованные строки кандидата")
        self._comparison = comparison
        self.setWindowTitle(tr("damper_candidate.details.title"))
        self.resize(1150, 600)
        notice = QLabel(tr("damper_candidate.details.notice"), self)
        notice.setWordWrap(True)
        context_label = QLabel(context, self)
        context_label.setTextFormat(Qt.TextFormat.PlainText)
        context_label.setWordWrap(True)
        self._filter = QComboBox(self)
        for key in ("all", "stop", "reserve_short", "missing", "clear"):
            self._filter.addItem(tr(f"damper_candidate.details.filter.{key}"), key)
        self._count = QLabel(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(tr("damper_candidate.details.filter_label"), self))
        controls.addWidget(self._filter)
        controls.addWidget(self._count, 1)
        self._table = QTableWidget(len(rows), len(columns), self)
        self._table.setHorizontalHeaderLabels(columns)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        for row_number, row in enumerate(rows):
            for column, raw in enumerate(row):
                displayed = f"{float(raw):.3f}" if column in (1, 2, 3, 4) and raw != "—" else raw
                item = QTableWidgetItem(displayed)
                item.setToolTip(raw)
                self._table.setItem(row_number, column, item)
        self._choose = QPushButton(tr("damper_candidate.details.choose"), self)
        self._choose.setEnabled(False)
        self._choose.clicked.connect(self._choose_row)
        self._table.cellDoubleClicked.connect(self._choose_row)
        self._table.currentCellChanged.connect(self._update_choice)
        self._filter.currentIndexChanged.connect(self._apply_filter)
        table_container = QWidget(self)
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addLayout(controls)
        table_layout.addWidget(self._table, 1)
        self._plot = DamperCandidatePlot(comparison, self)
        self._plot.rowSelected.connect(self._select_plot_row)
        self._plot_selection = QLabel(tr("damper_candidate.plot.selection_empty"), self)
        self._plot_selection.setWordWrap(True)
        plot_notice = QLabel(tr("damper_candidate.plot.legend"), self)
        plot_notice.setWordWrap(True)
        lower = comparison.limits.compressed_mm + comparison.reserve_mm
        upper = comparison.limits.extended_mm - comparison.reserve_mm
        if lower > upper:
            plot_notice.setText(plot_notice.text() + "\n" + tr("damper_candidate.plot.crossed"))
        elif lower == upper:
            plot_notice.setText(plot_notice.text() + "\n" + tr("damper_candidate.plot.touching"))
        graph_container = QWidget(self)
        graph_layout = QVBoxLayout(graph_container)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.addWidget(self._plot, 1)
        graph_layout.addWidget(self._plot_selection)
        graph_layout.addWidget(plot_notice)
        self._tabs = QTabWidget(self)
        self._tabs.addTab(table_container, tr("damper_candidate.plot.table_tab"))
        self._tabs.addTab(graph_container, tr("damper_candidate.plot.graph_tab"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("analysis.close"))
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self._choose)
        bottom.addStretch()
        bottom.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addWidget(context_label)
        layout.addWidget(self._tabs, 1)
        layout.addLayout(bottom)
        self._apply_filter()

    def _apply_filter(self, *_args: object) -> None:
        selected = self._filter.currentData()
        visible = 0
        self._table.clearSelection()
        self._table.setCurrentCell(-1, -1)
        for row, point in enumerate(self._comparison.points):
            show = selected == "all" or point.status == selected
            self._table.setRowHidden(row, not show)
            visible += int(show)
        self._choose.setEnabled(False)
        self._count.setText(tr("damper_candidate.details.count", visible=visible, total=len(self._comparison.points)))

    def _update_choice(self, row: int, *_args: object) -> None:
        self._choose.setEnabled(0 <= row < self._table.rowCount() and not self._table.isRowHidden(row))
        self._plot.set_row(row)
        if 0 <= row < len(self._comparison.points):
            point = self._comparison.points[row]
            length = f"{point.length_mm:.3f}" if point.length_mm is not None else "—"
            self._plot_selection.setText(tr("damper_candidate.plot.selection", row=row + 1,
                                             travel=f"{point.travel_mm:+.3f}", length=length,
                                             status=tr(f"damper_candidate.report.status.{point.status}")))
        else:
            self._plot_selection.setText(tr("damper_candidate.plot.selection_empty"))

    def _select_plot_row(self, row: int) -> None:
        if 0 <= row < self._table.rowCount():
            if self._table.isRowHidden(row):
                self._filter.setCurrentIndex(self._filter.findData("all"))
            self._table.setCurrentCell(row, 0)

    def _choose_row(self, *_args: object) -> None:
        row = self._table.currentRow()
        if 0 <= row < self._table.rowCount() and not self._table.isRowHidden(row):
            self.rowSelected.emit(row)
            self.accept()
