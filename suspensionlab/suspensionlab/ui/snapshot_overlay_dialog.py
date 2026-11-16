"""Наложение исходных точек А и Б в трёх плоских проекциях."""
from __future__ import annotations

from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.snapshot_compare import PointComparison
from ..core.snapshot_overlay import Projection, make_overlay
from ..i18n import tr
from .canvas.snapshot_overlay import SnapshotOverlayCanvas
from .controller import AppController


class SnapshotOverlayDialog(QDialog):
    def __init__(self, controller: AppController, rows: tuple[PointComparison, ...], parent: QWidget | None = None,
                 *, initial_role: str = "front", source_a: str = "", source_b: str = "", types: str = "") -> None:
        super().__init__(parent)
        self.rows = rows
        self.selected_row: int | None = None
        self._stale = False
        self.setWindowTitle(tr("snapshot_overlay.title"))
        self.resize(1050, 680)
        layout = QVBoxLayout(self)
        notice = QLabel(tr("snapshot_overlay.notice"))
        notice.setWordWrap(True)
        layout.addWidget(notice)
        if source_a or source_b:
            sources = QHBoxLayout()
            for key, source_value in (("source_a", source_a), ("source_b", source_b)):
                sources.addWidget(QLabel(tr("snapshot_compare." + key)))
                field = QLineEdit(source_value, self)
                field.setReadOnly(True)
                field.setToolTip(source_value)
                sources.addWidget(field, 1)
            layout.addLayout(sources)
        if types:
            types_label = QLabel(types, self)
            types_label.setTextFormat(Qt.TextFormat.PlainText)
            types_label.setWordWrap(True)
            layout.addWidget(types_label)
        controls = QHBoxLayout()
        self._role = QComboBox(self)
        for role in ("front", "rear"):
            self._role.addItem(tr("tree." + role), role)
        self._role.setCurrentIndex(max(0, self._role.findData(initial_role)))
        self._projection = QComboBox(self)
        for mode in ("front", "side", "top"):
            self._projection.addItem(tr(f"snapshot_overlay.view_{mode}"), mode)
        self._filter = QComboBox(self)
        for status in ("all", "changed", "unchanged", "added", "removed", "incompatible", "invalid"):
            self._filter.addItem(tr(f"snapshot_compare.filter_{status}"), status)
        controls.addWidget(self._role)
        controls.addWidget(self._projection)
        controls.addWidget(self._filter)
        self._zoom = QComboBox(self)
        for value in (1, 2, 4, 8):
            self._zoom.addItem(tr("snapshot_overlay.zoom_fit") if value == 1 else f"{value}×", float(value))
        controls.addWidget(self._zoom)
        controls.addStretch(1)
        layout.addLayout(controls)
        self._counts = QLabel(self)
        self._counts.setWordWrap(True)
        layout.addWidget(self._counts)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._list = QListWidget(self)
        self._list.setMinimumWidth(220)
        splitter.addWidget(self._list)
        self._canvas = SnapshotOverlayCanvas(rows, self)
        splitter.addWidget(self._canvas)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 700])
        layout.addWidget(splitter, 1)
        self._detail = QLabel(self)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)
        buttons = QHBoxLayout()
        self._choose = QPushButton(tr("snapshot_overlay.choose"))
        self._choose.clicked.connect(self._return_row)
        buttons.addWidget(self._choose)
        buttons.addStretch(1)
        close = QPushButton(tr("point_table.close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._role.currentIndexChanged.connect(self._update_view)
        self._projection.currentIndexChanged.connect(self._update_view)
        self._filter.currentIndexChanged.connect(self._update_view)
        self._zoom.currentIndexChanged.connect(self._update_zoom)
        self._list.currentItemChanged.connect(self._selection_changed)
        self._canvas.rowSelected.connect(self._pick_row)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._invalidate)
        self._update_view()

    def _update_view(self, *_args: object) -> None:
        if self._stale:
            return
        role = self._role.currentData()
        view = cast(Projection, self._projection.currentData())
        status = self._filter.currentData()
        previous = self._current_row()
        self._data = make_overlay(self.rows, role, view)
        visible = frozenset(i for i, row in enumerate(self.rows)
                            if row.role == role and status in ("all", row.status))
        self._list.blockSignals(True)
        self._list.clear()
        for i, row in enumerate(self.rows):
            if i not in visible:
                continue
            point = row.new or row.old
            name = tr(point.name_key) if point and point.name_key else row.code
            item = QListWidgetItem(f"{row.code} — {name} · {tr('snapshot_compare.status_' + row.status)}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)
            if i == previous:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)
        omitted = sum(i in visible for i in self._data.omitted_rows)
        self._counts.setText(tr("snapshot_overlay.count", shown=len(visible),
                                total=sum(row.role == role for row in self.rows), omitted=omitted,
                                axes=tr(f"snapshot_overlay.axes_{view}")))
        self._canvas.set_data(self._data, visible, self._current_row())
        self._selection_changed()

    def _update_zoom(self, *_args: object) -> None:
        self._canvas.set_zoom(self._zoom.currentData())

    def _current_row(self) -> int:
        item = self._list.currentItem()
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return value if isinstance(value, int) and 0 <= value < len(self.rows) else -1

    def _selection_changed(self, *_args: object) -> None:
        index = self._current_row()
        self._canvas.set_data(self._data, self._canvas.visible, index)
        self._choose.setEnabled(index >= 0 and not self._stale)
        if index < 0:
            self._detail.setText(tr("snapshot_overlay.select_hint"))
            return
        row = self.rows[index]
        old = repr(row.old.xyz) if row.old else "—"
        new = repr(row.new.xyz) if row.new else "—"
        delta = repr(row.delta) if row.delta is not None else "—"
        distance = repr(row.distance) if row.distance is not None else "—"
        self._detail.setText(tr("snapshot_overlay.selection", code=row.code,
                                status=tr("snapshot_compare.status_" + row.status),
                                old=old, new=new, delta=delta, distance=distance))

    def _pick_row(self, row: int) -> None:
        if self._stale:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == row:
                self._list.setCurrentItem(item)
                self._list.scrollToItem(item)
                return

    def _return_row(self) -> None:
        row = self._current_row()
        if not self._stale and row >= 0:
            self.selected_row = row
            self.accept()

    def _invalidate(self) -> None:
        self._stale = True
        for widget in (self._role, self._projection, self._filter, self._zoom, self._list, self._canvas, self._choose):
            widget.setEnabled(False)
        self._detail.setText(tr("snapshot_overlay.stale"))
