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
    QVBoxLayout,
    QWidget,
)

from ..core.spring_candidate import SpringComparison
from ..export.csv_report import CSVReport
from ..i18n import tr


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
        layout.addWidget(notice)
        layout.addLayout(controls)
        layout.addWidget(self._table, 1)
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

    def _choose_row(self, *_args: object) -> None:
        row = self._table.currentRow()
        if 0 <= row < self._table.rowCount() and not self._table.isRowHidden(row):
            self.accept()
            self.rowSelected.emit(row)
