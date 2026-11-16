"""Таблица исходных точек схемы с атомарной пакетной правкой."""
from __future__ import annotations

import csv
import math
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..diagnostic_events import event
from ..i18n import tr
from ..model.units import LENGTH_UNITS, UnitConversionError, UnitKind
from .controller import AppController


class PointTableDialog(QDialog):
    """Редактирует только хранимые координаты, не отражённые копии."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._applying = False
        self._stale = False
        self._changed: set[tuple[int, int]] = set()
        self._rows: list[tuple[str, str]] = []
        self.setWindowTitle(tr("point_table.title"))
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        note = QLabel(tr("point_table.note"))
        note.setWordWrap(True)
        layout.addWidget(note)
        self._filter = QComboBox()
        for value in ("all", "front", "rear"):
            self._filter.addItem(tr(f"point_table.filter_{value}"), value)
        self._filter.currentIndexChanged.connect(self._filter_rows)
        layout.addWidget(self._filter)
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels([tr(f"point_table.{key}") for key in
                                               ("axle", "code", "name", "representation", "x", "y", "z")])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        layout.addWidget(self._table)
        self._message = QLabel("")
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        actions = QHBoxLayout()
        self._export = QPushButton(tr("point_table.export"))
        self._export.clicked.connect(self._save_csv)
        actions.addWidget(self._export)
        actions.addStretch()
        self._apply = QPushButton(tr("point_table.apply"))
        self._apply.clicked.connect(self._apply_changes)
        actions.addWidget(self._apply)
        close = QPushButton(tr("point_table.close"))
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._populate()
        self._table.itemChanged.connect(self._item_changed)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._invalidate)

    def _populate(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._rows.clear()
        self._changed.clear()
        factor = LENGTH_UNITS[self._controller.units.length]
        for role in ("front", "rear"):
            axle = self._controller.project.axle(role)
            for code in axle.point_codes():
                point = axle.hardpoints.get(code)
                if point is None:
                    continue
                spec = axle.spec.point(code)
                representation = ("mirror" if spec and spec.mirrored else
                                  "explicit" if spec and spec.side != "center" else "single")
                row = len(self._rows)
                self._rows.append((role, code))
                self._table.insertRow(row)
                texts = [tr(f"tree.{role}"), code, tr(spec.name_key) if spec else code,
                         tr(f"point_table.{representation}")]
                texts.extend(repr(value / factor) for value in point.as_tuple())
                for col, text in enumerate(texts):
                    item = QTableWidgetItem(text)
                    locked = col >= 4 and (point.locked or self._controller.is_locked(
                        f"{role}.point.{code}.{'xyz'[col - 4]}"))
                    if col < 4 or locked:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if locked:
                        item.setToolTip(tr("point_table.locked"))
                    self._table.setItem(row, col, item)
        self._table.blockSignals(False)
        self._message.setText(tr("point_table.unit", unit=tr("unit.length." + self._controller.units.length)))
        self._filter_rows()

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() >= 4:
            self._changed.add((item.row(), item.column()))

    def _filter_rows(self) -> None:
        role = self._filter.currentData()
        for row, (row_role, _) in enumerate(self._rows):
            self._table.setRowHidden(row, role != "all" and role != row_role)

    def _finish_editor(self) -> None:
        """Фиксирует активное поле в черновике до применения или закрытия."""
        for editor in self._table.viewport().findChildren(QLineEdit):
            if editor.isVisible():
                delegate = self._table.itemDelegate()
                delegate.commitData.emit(editor)
                delegate.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def _invalidate(self) -> None:
        if self._applying:
            return
        self._finish_editor()
        self._stale = True
        self._apply.setEnabled(False)
        self._export.setEnabled(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._message.setText(tr("point_table.stale"))

    def _apply_changes(self) -> None:
        self._finish_editor()
        if self._stale:
            return
        edits: dict[tuple[str, str], list[float]] = {}
        for row, col in sorted(self._changed):
            role, code = self._rows[row]
            point = self._controller.project.axle(role).hardpoints[code]
            if point.locked or self._controller.is_locked(f"{role}.point.{code}.{'xyz'[col - 4]}"):
                event("points.apply", warning=True, result="locked", cells=len(self._changed))
                self._message.setText(tr("point_table.locked"))
                return
            item = self._table.item(row, col)
            assert item is not None
            try:
                value = self._controller.units.parse(item.text(), UnitKind.LENGTH)
                if not math.isfinite(value) or abs(value) > 1_000_000_000:
                    raise ValueError
            except (UnitConversionError, ValueError, OverflowError):
                if self._table.isRowHidden(row):
                    self._filter.setCurrentIndex(0)
                self._table.setCurrentCell(row, col)
                event("points.apply", warning=True, result="invalid", cells=len(self._changed))
                self._message.setText(tr("point_table.invalid", code=code, axis="XYZ"[col - 4]))
                return
            coords = edits.setdefault((role, code), list(point.as_tuple()))
            coords[col - 4] = value
        self._applying = True
        try:
            self._controller.move_points({key: tuple(values) for key, values in edits.items()})
            event("points.apply", result="ok", points=len(edits), cells=len(self._changed))
            self._populate()
            self._message.setText(tr("point_table.applied"))
        finally:
            self._applying = False

    def _save_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("point_table.export"), "points.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            self.export_csv(Path(path))
        except OSError as error:
            QMessageBox.warning(self, tr("point_table.export"), str(error))

    def export_csv(self, path: Path) -> None:
        """Экспортирует модель, не незафиксированные правки и не отражённые копии."""
        if self._stale:
            raise ValueError("stale point table")
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["axle", "type", "code", "name", "representation", "x_mm", "y_mm", "z_mm",
                             "point_locked", "x_locked", "y_locked", "z_locked"])
            for role, code in self._rows:
                axle = self._controller.project.axle(role)
                point = axle.hardpoints[code]
                spec = axle.spec.point(code)
                representation = ("mirrored" if spec and spec.mirrored else
                                  "explicit_side" if spec and spec.side != "center" else "single")
                writer.writerow([role, axle.type_code, code, tr(spec.name_key) if spec else code, representation,
                                 *point.as_tuple(), point.locked, *[self._controller.is_locked(
                                     f"{role}.point.{code}.{axis}") for axis in "xyz"]])

    def reject(self) -> None:
        self._finish_editor()
        if self._changed and QMessageBox.question(self, tr("point_table.title"), tr("point_table.discard")) != QMessageBox.StandardButton.Yes:
            return
        super().reject()
