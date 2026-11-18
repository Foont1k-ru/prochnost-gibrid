"""Read-only эксперимент совмещения ручных координат с точками проекта."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QSettings, Signal
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

from ..config import autosave_path, settings_path
from ..core.cad_registration import MAX_PAIRS, DistanceComparison, RegistrationEvaluation, evaluate_registration
from ..core.cad_registration_overlay import overlay_pairs
from ..core.cad_source_guard import summarize_sources
from ..export.cad_registration_report import distance_report, registration_report
from ..export.csv_report import CSVReport, write_csv_report
from ..i18n import tr
from ..model.point_csv import PointRecord, capture_points
from .cad_registration_overlay_dialog import CadRegistrationOverlayDialog
from .cad_registration_picker import CadRegistrationPicker
from .controller import AppController


class CadRegistrationDialog(QDialog):
    registrationChanged = Signal()

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._records = capture_points(controller.project)
        self._stale = False
        self._revision = 0
        self._source_digests: dict[QLabel, bytes] = {}
        self._snapshot_digest: bytes | None = None
        self._picker: CadRegistrationPicker | None = None
        self._report: CSVReport | None = None
        self._distance_report: CSVReport | None = None
        self._snapshot: tuple[tuple[PointRecord, ...], tuple[bool, ...], RegistrationEvaluation] | None = None
        self.setWindowTitle(tr("cad_registration.title"))
        self.resize(1100, 750)
        layout = QVBoxLayout(self)
        notice = QLabel(tr("cad_registration.notice"), self)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self._table = QTableWidget(0, 6, self)
        self._table.setHorizontalHeaderLabels([tr("cad_registration.point"), "CAD X, mm", "CAD Y, mm", "CAD Z, mm",
                                               tr("cad_registration.purpose"), tr("cad_registration.input_source")])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)
        buttons = QHBoxLayout()
        self._add = QPushButton(tr("cad_registration.add"), self)
        self._remove = QPushButton(tr("cad_registration.remove"), self)
        self._add.clicked.connect(self._add_row)
        self._remove.clicked.connect(self._remove_row)
        self._pick = QPushButton(tr("cad_registration.pick_button"), self)
        self._pick.clicked.connect(self._pick_for_row)
        buttons.addWidget(self._add)
        buttons.addWidget(self._remove)
        buttons.addWidget(self._pick)
        buttons.addStretch()
        layout.addLayout(buttons)
        self._source_status = QLabel(self)
        self._source_status.setWordWrap(True)
        layout.addWidget(self._source_status)
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
        self._export_distances = QPushButton(tr("cad_registration.distance_export"), self)
        self._export_distances.setEnabled(False)
        self._export_distances.clicked.connect(self._save_distances)
        run_row.addWidget(self._export_distances)
        self._overlay = QPushButton(tr("cad_registration_overlay.button"), self)
        self._overlay.setEnabled(False)
        self._overlay.clicked.connect(self._open_overlay)
        run_row.addWidget(self._overlay)
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
        self.registrationChanged.emit()
        self._revision += 1
        self._report = None
        self._distance_report = None
        self._snapshot = None
        self._snapshot_digest = None
        self._update_source_status()
        self._export.setEnabled(False)
        self._export_distances.setEnabled(False)
        self._overlay.setEnabled(False)
        self._result.clear()

    def _source_summary(self):
        digests = []
        for row in range(self._table.rowCount()):
            label = self._table.cellWidget(row, 5)
            assert isinstance(label, QLabel)
            digests.append(self._source_digests.get(label))
        return summarize_sources(tuple(digests))

    def _update_source_status(self) -> None:
        summary = self._source_summary()
        self._source_status.setText(tr("cad_registration.source_status", known=summary.known_points,
                                       unknown=summary.unknown_points, sources=summary.distinct_sources) +
                                    (" " + tr("cad_registration.source_conflict") if summary.has_conflict else ""))

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
        source = QLabel(self._table)
        self._set_source(source, "manual_or_edited")
        self._table.setCellWidget(row, 5, source)
        for column in range(1, 4):
            edit = QLineEdit(self._table)
            edit.setPlaceholderText("mm")
            edit.textChanged.connect(lambda _text, label=source: self._coordinate_changed(label))
            self._table.setCellWidget(row, column, edit)
        purpose = QComboBox(self._table)
        purpose.addItem(tr("cad_registration.fit"), True)
        purpose.addItem(tr("cad_registration.control"), False)
        purpose.currentIndexChanged.connect(self._clear_result)
        self._table.setCellWidget(row, 4, purpose)
        self._add.setEnabled(self._table.rowCount() < MAX_PAIRS)
        self._clear_result()

    @staticmethod
    def _set_source(label: QLabel, source: str) -> None:
        label.setProperty("cad_source", source)
        label.setText(tr(f"cad_registration.source_{source}"))
        label.setToolTip(tr("cad_registration.source_hint"))

    def _coordinate_changed(self, source: QLabel) -> None:
        self._source_digests.pop(source, None)
        self._set_source(source, "manual_or_edited")
        self._clear_result()

    def _pick_for_row(self) -> None:
        if self._stale:
            return
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("cad_registration.pick_title"), tr("cad_registration.pick_row"))
            return
        source = self._table.cellWidget(row, 5)
        fields = [self._table.cellWidget(row, column) for column in range(1, 4)]
        if not isinstance(source, QLabel) or not all(isinstance(field, QLineEdit) for field in fields):
            return
        revision = self._revision
        if self._picker is None:
            settings = QSettings(str(settings_path()), QSettings.Format.IniFormat)
            self._picker = CadRegistrationPicker(settings, self)
        picker = self._picker
        picker.chosen = None
        picker.chosen_digest = None
        accepted = picker.exec() == QDialog.DialogCode.Accepted
        point = picker.chosen
        digest = picker.chosen_digest
        if (not accepted or point is None or not isinstance(digest, bytes) or len(digest) != 32 or self._stale or revision != self._revision or
                self._table.cellWidget(row, 5) is not source or
                any(self._table.cellWidget(row, i) is not field for i, field in enumerate(fields, 1))):
            return
        if len(point) != 3 or any(not math.isfinite(value) for value in point):
            return
        for field, value in zip(fields, point, strict=True):
            assert isinstance(field, QLineEdit)
            previous = field.blockSignals(True)
            try:
                field.setText(repr(float(value)))
            finally:
                field.blockSignals(previous)
        self._source_digests[source] = digest
        self._set_source(source, "surface_preview")
        self._clear_result()

    def _remove_row(self) -> None:
        if self._stale or self._table.rowCount() <= 3:
            return
        row = self._table.currentRow()
        if row < 0:
            row = self._table.rowCount() - 1
        source = self._table.cellWidget(row, 5)
        if isinstance(source, QLabel):
            self._source_digests.pop(source, None)
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
        self._pick.setEnabled(False)
        self._result.setPlainText(tr("cad_registration.stale"))

    def _run(self) -> None:
        if self._stale:
            return
        self._clear_result()
        if not self._confirmed.isChecked():
            self._result.setPlainText(tr("cad_registration.confirm_required"))
            return
        summary = self._source_summary()
        if summary.has_conflict:
            self._result.setPlainText(tr("cad_registration.source_conflict"))
            return
        cad: list[tuple[float, float, float]] = []
        records = []
        fit_mask: list[bool] = []
        sources: list[str] = []
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
                label = self._table.cellWidget(row, 5)
                assert isinstance(label, QLabel)
                sources.append(label.property("cad_source"))
            points = tuple(cad)
            mask = tuple(fit_mask)
            result = evaluate_registration(points, tuple(record.xyz for record in records), mask)
            report = registration_report(result, tuple(records), points, mask, tr, tuple(sources), summary)
            distances_report = distance_report(result, tuple(records), mask, tr)
        except ValueError as error:
            code = str(error)
            if code not in ("selection", "coordinates", "count", "degenerate", "duplicate"):
                code = "coordinates"
            self._result.setPlainText(tr(f"cad_registration.error_{code}"))
            return
        transform = result.fit.transform
        lines = [tr("cad_registration.output"), self._source_status.text(),
                 tr("cad_registration.source_check_warning"), "", tr("cad_registration.rotation")]
        lines.extend("  ".join(f"{value:.10g}" for value in row) for row in transform.rotation)
        lines.extend([tr("cad_registration.translation"),
                      "  ".join(f"{value:.10g}" for value in transform.translation), "",
                      tr("cad_registration.fit_summary", count=sum(mask), rms=f"{result.fit.rms_mm:.6g}",
                         max=f"{result.fit.max_mm:.6g}"),
                      (tr("cad_registration.no_controls") if result.control_rms_mm is None else
                       tr("cad_registration.control_summary", count=len(mask) - sum(mask),
                          rms=f"{result.control_rms_mm:.6g}", max=f"{result.control_max_mm:.6g}")),
                      "", tr("cad_registration.distance_warning")])
        def distance_line(label: str, value: DistanceComparison | None) -> str:
            if value is None:
                return tr("cad_registration.distance_none", group=label)
            return tr("cad_registration.distance_summary", group=label, count=value.count,
                      rms=f"{value.rms_difference_mm:.6g}", row1=value.first_row + 1,
                      row2=value.second_row + 1, cad=f"{value.cad_length_mm:.6g}",
                      project=f"{value.project_length_mm:.6g}", diff=f"{value.difference_mm:.6g}")
        lines.extend([distance_line(tr("cad_registration.distance_fit"), result.fit_distances),
                      distance_line(tr("cad_registration.distance_control"), result.control_distances),
                      "", tr("cad_registration.residuals")])
        for i, (record, point, is_fit) in enumerate(zip(records, result.points, mask, strict=True), 1):
            delta = ", ".join(f"{value:.6g}" for value in point.delta_mm)
            lines.append(f"{i}: {tr('cad_registration.fit' if is_fit else 'cad_registration.control')} / "
                         f"{record.role} / {record.code}: Δ=({delta}) mm; {point.distance_mm:.6g} mm")
        lines.extend(["", tr("cad_registration.distance_list")])
        for segment in sorted(result.segments, key=lambda item: (-abs(item.difference_mm), item.first_row, item.second_row)):
            group = tr("cad_registration.distance_control" if segment.involves_control else "cad_registration.distance_fit")
            lines.append(tr("cad_registration.distance_entry", row1=segment.first_row + 1, row2=segment.second_row + 1,
                            group=group, cad=f"{segment.cad_length_mm:.6g}",
                            project=f"{segment.project_length_mm:.6g}", diff=f"{segment.difference_mm:.6g}"))
        self._result.setPlainText("\n".join(lines))
        self._result.moveCursor(self._result.textCursor().MoveOperation.Start)
        self._report = report
        self._distance_report = distances_report
        self._snapshot = (tuple(records), mask, result)
        self._snapshot_digest = next(iter(self._source_digests.values()), None)
        self._export.setEnabled(True)
        self._export_distances.setEnabled(True)
        self._overlay.setEnabled(True)

    def _open_overlay(self) -> None:
        if self._stale or self._snapshot is None:
            return
        records, mask, result = self._snapshot
        try:
            pairs = overlay_pairs(records, mask, result)
        except ValueError:
            QMessageBox.warning(self, tr("export.error_title"), tr("cad_registration_overlay.coordinates_error"))
            return
        settings = QSettings(str(settings_path()), QSettings.Format.IniFormat)
        dialog = CadRegistrationOverlayDialog(self.controller, result.fit.transform, pairs, settings, self,
                                              expected_digest=self._snapshot_digest)
        self.registrationChanged.connect(dialog._invalidate)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _save_report(self) -> None:
        self._save_csv(False)

    def _save_distances(self) -> None:
        self._save_csv(True)

    def _save_csv(self, distances: bool) -> None:
        report = self._distance_report if distances else self._report
        if self._stale or report is None:
            return
        revision = self._revision
        default = "cad_registration_distances.csv" if distances else "cad_registration.csv"
        selected, _ = QFileDialog.getSaveFileName(self, tr("export.title"), default, tr("export.filter"))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".csv":
            path = path.with_name(path.name + ".csv")
        try:
            if (self._stale or revision != self._revision or
                    report is not (self._distance_report if distances else self._report)):
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
