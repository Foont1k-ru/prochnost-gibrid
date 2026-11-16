"""Просмотр предварительного сравнения линий опор без изменений проекта."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from ..core.axis_alignment import AxisAlignmentRow
from ..export.csv_report import CSVReport
from ..i18n import tr
from .table_export import save_table_dialog


class AxisAlignmentDialog(QDialog):
    rowSelected = Signal(int)

    def __init__(self, rows: tuple[AxisAlignmentRow, ...], report: CSVReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if len(report.rows) != len(rows) or len(report.columns) != 11 or any(len(row) != 11 for row in report.rows):
            raise ValueError(tr("export.no_results"))
        self.setWindowTitle(tr("axis_alignment.title"))
        self.resize(900, 510)
        self._report = report
        self._table = QTableWidget(len(rows), len(report.columns), self)
        self._table.setHorizontalHeaderLabels(report.columns)
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
                       f"{result.upper_axial_mm:+.4f}" if result else "—", values[9], values[10])
            for col, text in enumerate(display):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self._table.setItem(row, col, item)
        notice = QLabel(tr("axis_alignment.notice"), self)
        notice.setWordWrap(True)
        self._count = QLabel(tr("axis_alignment.count", available=sum(row.result is not None for row in rows), total=len(rows)), self)
        self._count.setWordWrap(True)
        self._choose = QPushButton(tr("axis_alignment.choose"), self)
        self._choose.setEnabled(False)
        self._choose.clicked.connect(self._select)
        self._table.currentCellChanged.connect(lambda row, *_: self._choose.setEnabled(0 <= row < len(rows)))
        self._export = QPushButton(tr("axis_alignment.export"), self)
        self._export.clicked.connect(lambda: save_table_dialog(self, self._report))
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
        layout.addWidget(self._table, 1)
        layout.addLayout(bottom)

    def _select(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < self._table.rowCount():
            self.rowSelected.emit(row)
            self.accept()
