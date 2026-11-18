"""Отдельная предварительная проверка кандидата без изменения проекта."""
from __future__ import annotations

from collections.abc import Callable
from math import isfinite

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.spring_candidate import (
    SpringCandidate,
    SpringComparison,
    compare_spring_candidate,
    summarize_candidate_force,
)
from ..core.spring_rate_estimate import SpringRatePoints
from ..export.csv_report import CSVReport
from ..i18n import tr
from .spring_candidate_points_dialog import SpringCandidatePointsDialog
from .spring_rate_dialog import MAX_CANDIDATE_RATE, SpringRateDialog
from .table_export import save_table_dialog


class SpringCandidateDialog(QDialog):
    rowSelected = Signal(int)
    snapshotInvalidated = Signal()

    def __init__(self, points: tuple[tuple[float, float | None], ...], reference_installed_mm: float,
                 context: str, parent: QWidget | None = None, *,
                 report_factory: Callable[[SpringComparison], CSVReport] | None = None,
                 balance_factory: Callable[[SpringCandidate], None] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("spring_candidate.title"))
        self.resize(680, 620)
        self._points = points
        self._reference_installed = reference_installed_mm
        self.comparison: SpringComparison | None = None
        self._rate_points: SpringRatePoints | None = None
        self._report_factory = report_factory
        self._balance_factory = balance_factory
        self.report: CSVReport | None = None
        self._details_dialog: SpringCandidatePointsDialog | None = None
        notice = QLabel(tr("spring_candidate.notice"), self)
        notice.setWordWrap(True)
        source = QLabel(context, self)
        source.setWordWrap(True)
        form = QFormLayout()
        self._fields = {key: QLineEdit(self) for key in ("free", "installed", "coil", "coil_reserve", "compression_reserve")}
        for key, edit in self._fields.items():
            edit.setPlaceholderText(tr("spring_candidate.required"))
            edit.textChanged.connect(self._clear)
            form.addRow(tr(f"spring_candidate.{key}"), edit)
        self._rate_source_label = QLabel(self)
        self._rate_source_label.setWordWrap(True)
        self._force_enable = QCheckBox(tr("spring_candidate.force.enable"), self)
        self._force_rate = QLineEdit(self)
        self._force_rate.setPlaceholderText(tr("spring_candidate.force.rate_placeholder"))
        self._force_rate.setToolTip(tr("spring_candidate.force.tip"))
        self._force_enable.setToolTip(tr("spring_candidate.force.tip"))
        self._force_rate.setEnabled(False)
        self._force_enable.toggled.connect(self._force_rate.setEnabled)
        self._force_enable.toggled.connect(self._clear)
        self._force_rate.textChanged.connect(self._clear)
        self._fields["free"].textChanged.connect(self._forget_rate_points)
        self._force_rate.textChanged.connect(self._forget_rate_points)
        self._force_enable.toggled.connect(self._forget_rate_points)
        self._estimate_rate = QPushButton(tr("spring_rate.open"), self)
        self._estimate_rate.setToolTip(tr("spring_rate.title"))
        self._estimate_rate.clicked.connect(self._open_rate_estimate)
        rate_row = QHBoxLayout()
        rate_row.addWidget(self._force_rate, 1)
        rate_row.addWidget(self._estimate_rate)
        form.addRow(self._force_enable, rate_row)
        form.addRow(self._rate_source_label)
        self._compare = QPushButton(tr("spring_candidate.compare"), self)
        self._compare.clicked.connect(self._calculate)
        self._result = QTextEdit(self)
        self._result.setReadOnly(True)
        self._force_min_row: int | None = None
        self._force_max_row: int | None = None
        self._force_min_button = QPushButton(tr("spring_candidate.force.go_min"), self)
        self._force_max_button = QPushButton(tr("spring_candidate.force.go_max"), self)
        self._force_min_button.clicked.connect(lambda: self._select_force_extremum(self._force_min_row))
        self._force_max_button.clicked.connect(lambda: self._select_force_extremum(self._force_max_row))
        self._balance = QPushButton(tr("spring_candidate.balance.button"), self)
        self._balance.setToolTip(tr("spring_candidate.balance.tip"))
        self._balance.clicked.connect(self._open_balance)
        self._details = QPushButton(tr("spring_candidate.details.button"), self)
        self._details.clicked.connect(self._open_details)
        self._export = QPushButton(tr("spring_candidate.report.button"), self)
        self._export.clicked.connect(self._save_report)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("analysis.close"))
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addWidget(source)
        layout.addLayout(form)
        layout.addWidget(self._compare)
        layout.addWidget(self._result, 1)
        force_actions = QHBoxLayout()
        force_actions.addWidget(self._force_min_button)
        force_actions.addWidget(self._force_max_button)
        layout.addLayout(force_actions)
        layout.addWidget(self._balance)
        actions = QHBoxLayout()
        actions.addWidget(self._details)
        actions.addWidget(self._export)
        layout.addLayout(actions)
        layout.addWidget(buttons)
        self.finished.connect(lambda _result: self._close_details())
        self._forget_rate_points()
        self._clear()

    def _forget_rate_points(self, *_args: object) -> None:
        self._rate_points = None
        mode = "manual" if self._force_enable.isChecked() else "disabled"
        self._rate_source_label.setText(tr(f"spring_rate.source_{mode}"))

    def _clear(self, *_args: object) -> None:
        if self.comparison is not None:
            self.snapshotInvalidated.emit()
        self._close_details()
        self.comparison = None
        self.report = None
        self._force_min_row = self._force_max_row = None
        self._balance.setEnabled(False)
        self._force_min_button.setEnabled(False)
        self._force_max_button.setEnabled(False)
        self._details.setEnabled(False)
        self._export.setEnabled(False)
        self._result.setPlainText(tr("spring_candidate.empty"))

    def _calculate(self) -> None:
        self._clear()
        try:
            def parse(key: str) -> float:
                value = float(self._fields[key].text().strip().replace(",", "."))
                if not isfinite(value) or not 0 <= value <= 2000:
                    raise ValueError
                return value
            rate = None
            if self._force_enable.isChecked():
                rate = float(self._force_rate.text().strip().replace(",", "."))
                if not isfinite(rate) or not 0 < rate <= MAX_CANDIDATE_RATE:
                    raise ValueError
            candidate = SpringCandidate(parse("free"), parse("installed"), parse("coil"), parse("coil_reserve"),
                                        parse("compression_reserve"), linear_rate_n_mm=rate,
                                        rate_points=self._rate_points if rate is not None else None)
            self.comparison = compare_spring_candidate(self._points, self._reference_installed, candidate)
        except (ValueError, OverflowError):
            self._result.setPlainText(tr("spring_candidate.invalid"))
            return
        comparison = self.comparison
        self._balance.setEnabled(self._balance_factory is not None and comparison.candidate.linear_rate_n_mm is not None)
        counts = {key: sum(point.status == key for point in comparison.points) for key in
                  ("missing", "invalid", "coil_bind", "uncompressed", "reserve_short", "clear")}
        lines = [tr("spring_candidate.counts", total=len(comparison.points), **counts)]
        for key in ("invalid", "coil_bind", "uncompressed", "reserve_short"):
            first = next(((i, point) for i, point in enumerate(comparison.points, 1) if point.status == key), None)
            if first:
                index, point = first
                lines.append(tr(f"spring_candidate.first.{key}", row=index, travel=f"{point.travel_mm:+.2f}"))
        if comparison.candidate.linear_rate_n_mm is None:
            lines.append(tr("spring_candidate.force.disabled"))
        else:
            summary = summarize_candidate_force(comparison)
            lines.append(tr("spring_candidate.force.count", rate=repr(comparison.candidate.linear_rate_n_mm),
                            available=summary.calculated, total=summary.total))
            lines.append(tr("spring_candidate.force.unavailable_counts", missing=summary.missing,
                            invalid=summary.invalid, coil_bind=summary.coil_bind, overflow=summary.overflow))
            if summary.minimum is not None and summary.maximum is not None:
                for key, extremum in (("minimum", summary.minimum), ("maximum", summary.maximum)):
                    lines.append(tr(f"spring_candidate.force.{key}", force=f"{extremum.force_n:.2f}",
                                    row=extremum.row + 1, travel=f"{extremum.travel_mm:+.2f}"))
                self._force_min_row = summary.minimum.row
                self._force_max_row = summary.maximum.row
                self._force_min_button.setEnabled(True)
                self._force_max_button.setEnabled(True)
                lines.append(tr("spring_candidate.force.extrema_notice"))
            else:
                lines.append(tr("spring_candidate.force.no_values"))
            lines.append(tr("spring_candidate.force.notice"))
        lines.append(tr("spring_candidate.result_notice"))
        if self._report_factory is not None:
            try:
                self.report = self._report_factory(comparison)
                self._export.setEnabled(True)
                self._details.setEnabled(True)
            except (ValueError, UnicodeError) as error:
                lines.append(tr("spring_candidate.report.unavailable", reason=str(error)))
        self._result.setPlainText("\n\n".join(lines))

    def _open_rate_estimate(self) -> None:
        free_length_text = self._fields["free"].text()
        dialog = SpringRateDialog(free_length_text, self)
        if (dialog.exec() == QDialog.DialogCode.Accepted and dialog.estimate is not None and dialog.points is not None
                and self._fields["free"].text() == free_length_text):
            self._force_enable.setChecked(True)
            self._force_rate.setText(repr(dialog.estimate.rate_n_mm))
            # Даже та же жёсткость может быть получена из других точек.
            self._clear()
            self._rate_points = dialog.points
            self._rate_source_label.setText(tr("spring_rate.source_two_points"))
        dialog.deleteLater()

    def _select_force_extremum(self, row: int | None) -> None:
        if row is not None:
            self._select_row(row)

    def _open_balance(self) -> None:
        if (self.comparison is not None and self.comparison.candidate.linear_rate_n_mm is not None
                and self._balance_factory is not None):
            self._balance_factory(self.comparison.candidate)

    def _close_details(self) -> None:
        if self._details_dialog is not None:
            dialog = self._details_dialog
            self._details_dialog = None
            dialog.reject()

    def _open_details(self) -> None:
        if self.comparison is None or self.report is None:
            return
        if self._details_dialog is not None:
            self._details_dialog.raise_()
            self._details_dialog.activateWindow()
            return
        dialog = SpringCandidatePointsDialog(self.comparison, self.report, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._details_dialog = dialog
        dialog.rowSelected.connect(self._select_row)
        dialog.finished.connect(lambda _result: self._forget_details(dialog))
        dialog.show()

    def _forget_details(self, dialog: SpringCandidatePointsDialog) -> None:
        if self._details_dialog is dialog:
            self._details_dialog = None

    def _select_row(self, row: int) -> None:
        if self.comparison is not None and 0 <= row < len(self.comparison.points):
            self.rowSelected.emit(row)
            self.accept()

    def _save_report(self) -> None:
        if self.report is not None:
            save_table_dialog(self, self.report)
