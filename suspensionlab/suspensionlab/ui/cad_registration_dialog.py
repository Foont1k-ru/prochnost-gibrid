"""Read-only эксперимент совмещения ручных координат с точками проекта."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from ..config import autosave_path
from ..core.cad_registration import MAX_PAIRS, evaluate_registration
from ..export.cad_registration_report import registration_report
from ..export.csv_report import CSVReport, write_csv_report
from ..i18n import tr
from ..model.point_csv import capture_points
from .controller import AppController


class CadRegistrationDialog(QDialog):
    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._records = capture_points(controller.project)
        self._stale = False
        self._revision = 0
        self._report: CSVReport | None = None
        self.setWindowTitle(tr("cad_registration.title"))
        self.resize(1100, 750)
        layout = QVBoxLayout(self)
        notice = QLabel(tr("cad_registration.notice"), self)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels([tr("cad_registration.point"), "CAD X, mm", "CAD Y, mm", "CAD Z, mm",
                                               tr("cad_registration.purpose")])
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
        run_row = QHBoxLayout()
        self._calculate = QPushButton(tr("cad_registration.calculate"), self)
        self._calculate.clicked.connect(self._run)
        self._export = QPushButton(tr("cad_registration.export"), self)
        self._export.setEnabled(False)
        self._export.clicked.connect(self._save_report)
        run_row.addWidget(self._calculate)
        run_row.addWidget(self._export)
        run_row.addStretch()
        layout.addLayout(run_row)
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
        controller.projectReplaced.connect(self._invalidate)

    def _clear_result(self, *_args) -> None:
        self._revision += 1
        self._report = None
        self._export.setEnabled(False)
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
        purpose = QComboBox(self._table)
        purpose.addItem(tr("cad_registration.fit"), True)
        purpose.addItem(tr("cad_registration.control"), False)
        purpose.currentIndexChanged.connect(self._clear_result)
        self._table.setCellWidget(row, 4, purpose)
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
        self._clear_result()
        self._table.setEnabled(False)
        self._confirmed.setEnabled(False)
        self._calculate.setEnabled(False)
        self._add.setEnabled(False)
        self._remove.setEnabled(False)
        self._result.setPlainText(tr("cad_registration.stale"))

    def _run(self) -> None:
        if self._stale:
            return
        self._clear_result()
        if not self._confirmed.isChecked():
            self._result.setPlainText(tr("cad_registration.confirm_required"))
            return
        cad: list[tuple[float, float, float]] = []
        records = []
        fit_mask: list[bool] = []
        selected: set[int] = set()
        try:
            for row in range(self._table.rowCount()):
                combo = self._table.cellWidget(row, 0)
                purpose = self._table.cellWidget(row, 4)
                assert isinstance(combo, QComboBox) and isinstance(purpose, QComboBox)
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
                cad.append((coords[0], coords[1], coords[2]))
                records.append(self._records[index])
                fit_mask.append(purpose.currentData() is True)
            points = tuple(cad)
            mask = tuple(fit_mask)
            result = evaluate_registration(points, tuple(record.xyz for record in records), mask)
            report = registration_report(result, tuple(records), points, mask, tr)
        except ValueError as error:
            code = str(error)
            if code not in ("selection", "coordinates", "count", "degenerate", "duplicate"):
                code = "coordinates"
            self._result.setPlainText(tr(f"cad_registration.error_{code}"))
            return
        transform = result.fit.transform
        lines = [tr("cad_registration.output"), "", tr("cad_registration.rotation")]
        lines.extend("  ".join(f"{value:.10g}" for value in row) for row in transform.rotation)
        lines.extend([tr("cad_registration.translation"),
                      "  ".join(f"{value:.10g}" for value in transform.translation), "",
                      tr("cad_registration.fit_summary", count=sum(mask), rms=f"{result.fit.rms_mm:.6g}",
                         max=f"{result.fit.max_mm:.6g}"),
                      (tr("cad_registration.no_controls") if result.control_rms_mm is None else
                       tr("cad_registration.control_summary", count=len(mask) - sum(mask),
                          rms=f"{result.control_rms_mm:.6g}", max=f"{result.control_max_mm:.6g}")),
                      tr("cad_registration.residuals")])
        for i, (record, point, is_fit) in enumerate(zip(records, result.points, mask, strict=True), 1):
            delta = ", ".join(f"{value:.6g}" for value in point.delta_mm)
            lines.append(f"{i}: {tr('cad_registration.fit' if is_fit else 'cad_registration.control')} / "
                         f"{record.role} / {record.code}: Δ=({delta}) mm; {point.distance_mm:.6g} mm")
        self._result.setPlainText("\n".join(lines))
        self._result.moveCursor(self._result.textCursor().MoveOperation.Start)
        self._report = report
        self._export.setEnabled(True)

    def _save_report(self) -> None:
        if self._stale or self._report is None:
            return
        report, revision = self._report, self._revision
        selected, _ = QFileDialog.getSaveFileName(self, tr("export.title"), "cad_registration.csv", tr("export.filter"))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".csv":
            path = path.with_name(path.name + ".csv")
        try:
            if self._stale or revision != self._revision or report is not self._report:
                raise ValueError(tr("snapshot_compare.export_changed"))
            protected = [autosave_path()]
            if self.controller.project.path:
                protected.append(Path(self.controller.project.path))
            if any(path.resolve() == target.resolve() or
                   (path.exists() and target.exists() and path.samefile(target)) for target in protected):
                raise ValueError(tr("point_import.export_project"))
            write_csv_report(report, path)
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
