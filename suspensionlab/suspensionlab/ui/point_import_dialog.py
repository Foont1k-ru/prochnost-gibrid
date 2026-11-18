"""Подтверждение изменений координат из CSV до применения к проекту."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..model.point_csv import PointChange
from .controller import AppController


class PointImportDialog(QDialog):
    def __init__(self, controller: AppController, changes: tuple[PointChange, ...], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("point_import.preview_title"))
        self.resize(950, 600)
        layout = QVBoxLayout(self)
        self._notice = QLabel(tr("point_import.preview_notice", points=len(changes),
                                 cells=sum(len(change.axes) for change in changes),
                                 outside=sum(change.outside_zone is True for change in changes)))
        self._notice.setWordWrap(True)
        layout.addWidget(self._notice)
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels([tr(f"point_import.column_{name}") for name in
                                               ("axle", "code", "representation", "axis", "old", "new", "zone")])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        for change in changes:
            zone = "unknown" if change.outside_zone is None else "outside" if change.outside_zone else "inside"
            for axis in change.axes:
                idx = "xyz".index(axis)
                row = self._table.rowCount()
                self._table.insertRow(row)
                representation = {"mirrored": "mirror", "explicit_side": "explicit", "single": "single"}
                values = (tr(f"tree.{change.point.role}"), change.point.code,
                          tr("point_table." + representation[change.point.representation]), axis.upper(),
                          repr(change.point.xyz[idx]), repr(change.new[idx]), tr(f"point_import.zone_{zone}"))
                for col, text in enumerate(values):
                    self._table.setItem(row, col, QTableWidgetItem(text))
        layout.addWidget(self._table)
        buttons = QDialogButtonBox(self)
        self._apply = buttons.addButton(tr("point_import.confirm"), QDialogButtonBox.ButtonRole.AcceptRole)
        self._apply.setEnabled(bool(changes))
        self._apply.setAutoDefault(False)
        self._apply.setDefault(False)
        cancel = buttons.addButton(tr("dialog.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._invalidate)

    def _invalidate(self) -> None:
        self._apply.setEnabled(False)
        self._notice.setText(tr("point_import.stale"))
