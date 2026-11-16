"""Read-only эксперимент совмещения ручных координат с точками проекта."""
from __future__ import annotations

import math

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from ..core.cad_registration import MAX_PAIRS, register_points
from ..i18n import tr
from ..model.point_csv import capture_points
from .controller import AppController


class CadRegistrationDialog(QDialog):
    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._records = capture_points(controller.project)
        self._stale = False
        self.setWindowTitle(tr("cad_registration.title"))
        self.resize(1000, 720)
        layout = QVBoxLayout(self)
        notice = QLabel(tr("cad_registration.notice"), self)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels([tr("cad_registration.point"), "CAD X, mm", "CAD Y, mm", "CAD Z, mm"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)
        buttons = QHBoxLayout()
        self._add = QPushButton(tr("cad_registration.add"), self)
        self._remove = QPushButton(tr("cad_registration.remove"), self)
        self._add.clicked.connect(self._add_row)
        self._remove.clicked.connect(self._remove_row)
        buttons.addWidget(self._add)
        buttons.addWidget(self._remove)
        buttons.addStretch()
        layout.addLayout(buttons)
        self._confirmed = QCheckBox(tr("cad_registration.confirm"), self)
        self._confirmed.toggled.connect(self._clear_result)
        layout.addWidget(self._confirmed)
        self._calculate = QPushButton(tr("cad_registration.calculate"), self)
        self._calculate.clicked.connect(self._run)
        layout.addWidget(self._calculate)
        self._result = QPlainTextEdit(self)
        self._result.setReadOnly(True)
        self._result.setPlaceholderText(tr("cad_registration.empty"))
        layout.addWidget(self._result, 1)
        self._close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self._close.rejected.connect(self.reject)
        layout.addWidget(self._close)
        for _ in range(3):
            self._add_row()
        controller.modelChanged.connect(self._invalidate)

    def _clear_result(self, *_args) -> None:
        self._result.clear()

    def _add_row(self) -> None:
        if self._stale or self._table.rowCount() >= MAX_PAIRS:
            return
        row = self._table.rowCount()
        self._table.insertRow(row)
        combo = QComboBox(self._table)
        combo.addItem(tr("cad_registration.select"), -1)
        for index, point in enumerate(self._records):
            name = tr(point.name_key) if point.name_key else point.code
            xyz = ", ".join(f"{value:.8g}" for value in point.xyz)
            combo.addItem(f"{point.role} / {point.code} / {name} / {point.representation} / ({xyz}) mm", index)
        combo.currentIndexChanged.connect(self._clear_result)
        self._table.setCellWidget(row, 0, combo)
        for column in range(1, 4):
            edit = QLineEdit(self._table)
            edit.setPlaceholderText("mm")
            edit.textChanged.connect(self._clear_result)
            self._table.setCellWidget(row, column, edit)
        self._add.setEnabled(self._table.rowCount() < MAX_PAIRS)
        self._clear_result()

    def _remove_row(self) -> None:
        if self._stale or self._table.rowCount() <= 3:
            return
        row = self._table.currentRow()
        if row < 0:
            row = self._table.rowCount() - 1
        self._table.removeRow(row)
        self._add.setEnabled(True)
        self._clear_result()

    def _invalidate(self) -> None:
        self._stale = True
        self._table.setEnabled(False)
        self._confirmed.setEnabled(False)
        self._calculate.setEnabled(False)
        self._add.setEnabled(False)
        self._remove.setEnabled(False)
        self._result.setPlainText(tr("cad_registration.stale"))

    def _run(self) -> None:
        if self._stale:
            return
        if not self._confirmed.isChecked():
            self._result.setPlainText(tr("cad_registration.confirm_required"))
            return
        cad = []
        target = []
        selected: set[int] = set()
        try:
            for row in range(self._table.rowCount()):
                combo = self._table.cellWidget(row, 0)
                assert isinstance(combo, QComboBox)
                index = combo.currentData()
                if not isinstance(index, int) or index < 0 or index in selected:
                    raise ValueError("selection")
                selected.add(index)
                coords = []
                for column in range(1, 4):
                    widget = self._table.cellWidget(row, column)
                    assert isinstance(widget, QLineEdit)
                    number = float(widget.text().strip().replace(",", "."))
                    if not math.isfinite(number):
                        raise ValueError("coordinates")
                    coords.append(number)
                cad.append(coords)
                target.append(self._records[index].xyz)
            result = register_points(cad, target)
        except ValueError as error:
            code = str(error)
            if code not in ("selection", "coordinates", "count", "degenerate"):
                code = "coordinates"
            self._result.setPlainText(tr(f"cad_registration.error_{code}"))
            return
        transform = result.transform
        lines = [tr("cad_registration.output"), "", tr("cad_registration.rotation")]
        lines.extend("  ".join(f"{value:.10g}" for value in row) for row in transform.rotation)
        lines.extend([tr("cad_registration.translation"),
                      "  ".join(f"{value:.10g}" for value in transform.translation), "",
                      tr("cad_registration.summary", rms=f"{result.rms_mm:.6g}", max=f"{result.max_mm:.6g}"),
                      tr("cad_registration.residuals")])
        lines.extend(f"{i + 1}: {value:.6g} mm" for i, value in enumerate(result.residuals_mm))
        self._result.setPlainText("\n".join(lines))
        self._result.moveCursor(self._result.textCursor().MoveOperation.Start)
