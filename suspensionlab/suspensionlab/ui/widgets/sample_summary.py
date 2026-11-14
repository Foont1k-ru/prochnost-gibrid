"""Навигация по группам соседних рассчитанных точек, не диапазонам допустимости."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.sample_summary import SampleCheck, SampleGroup, group_samples
from ...i18n import tr


class SampleSummary(QWidget):
    """Список подряд идущих строк; выбор переводит основную таблицу на точку."""

    rowSelected = Signal(int)

    def __init__(self, parent: QWidget | None = None, *, two_sides: bool = False) -> None:
        super().__init__(parent)
        self._two_sides = two_sides
        self.groups: tuple[SampleGroup, ...] = ()
        notice = QLabel(tr("summary.notice_two" if two_sides else "summary.notice"), self)
        notice.setWordWrap(True)
        columns = ("status", "first_left", "last_left", "first_right", "last_right", "count") if two_sides else (
            "status", "first", "last", "count")
        self._table = QTableWidget(0, len(columns), self)
        self._table.setHorizontalHeaderLabels([tr(f"summary.column.{key}") for key in columns])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.cellClicked.connect(self._choose_first)
        self._first = QPushButton(tr("summary.first"), self)
        self._last = QPushButton(tr("summary.last"), self)
        self._first.clicked.connect(self._choose_first)
        self._last.clicked.connect(self._choose_last)
        buttons = QHBoxLayout()
        buttons.addWidget(self._first)
        buttons.addWidget(self._last)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(notice)
        layout.addWidget(self._table, 1)
        layout.addLayout(buttons)
        self.set_samples(())

    def set_samples(self, samples: tuple[SampleCheck, ...]) -> None:
        if self._two_sides and any(point.right_travel_mm is None for point in samples):
            raise ValueError("Не заданы ходы обеих сторон")
        self.groups = group_samples(samples)
        self._table.setRowCount(len(self.groups))
        for row, group in enumerate(self.groups):
            values = [tr(f"summary.status.{group.first.status}"), f"{group.first.travel_mm:+.2f}",
                      f"{group.last.travel_mm:+.2f}"]
            if self._two_sides:
                first_right, last_right = group.first.right_travel_mm, group.last.right_travel_mm
                assert first_right is not None and last_right is not None
                values.extend((f"{first_right:+.2f}", f"{last_right:+.2f}"))
            values.append(str(group.count))
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self._table.setItem(row, col, item)
        self._first.setEnabled(bool(self.groups))
        self._last.setEnabled(bool(self.groups))
        if self.groups:
            self._table.setCurrentCell(0, 0)

    def _choose_first(self, *_args: object) -> None:
        index = self._table.currentRow()
        if 0 <= index < len(self.groups):
            self.rowSelected.emit(self.groups[index].first_row)

    def _choose_last(self, *_args: object) -> None:
        index = self._table.currentRow()
        if 0 <= index < len(self.groups):
            self.rowSelected.emit(self.groups[index].last_row)
