"""Отдельная предварительная проверка кандидата без изменения проекта."""
from __future__ import annotations

from collections.abc import Callable
from math import isfinite

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.spring_candidate import SpringCandidate, SpringComparison, compare_spring_candidate
from ..export.csv_report import CSVReport
from ..i18n import tr
from .table_export import save_table_dialog


class SpringCandidateDialog(QDialog):
    def __init__(self, points: tuple[tuple[float, float | None], ...], reference_installed_mm: float,
                 context: str, parent: QWidget | None = None, *,
                 report_factory: Callable[[SpringComparison], CSVReport] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("spring_candidate.title"))
        self.resize(680, 620)
        self._points = points
        self._reference_installed = reference_installed_mm
        self.comparison: SpringComparison | None = None
        self._report_factory = report_factory
        self.report: CSVReport | None = None
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
        self._compare = QPushButton(tr("spring_candidate.compare"), self)
        self._compare.clicked.connect(self._calculate)
        self._result = QTextEdit(self)
        self._result.setReadOnly(True)
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
        layout.addWidget(self._export)
        layout.addWidget(buttons)
        self._clear()

    def _clear(self, *_args: object) -> None:
        self.comparison = None
        self.report = None
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
            candidate = SpringCandidate(*(parse(key) for key in ("free", "installed", "coil", "coil_reserve", "compression_reserve")))
            self.comparison = compare_spring_candidate(self._points, self._reference_installed, candidate)
        except (ValueError, OverflowError):
            self._result.setPlainText(tr("spring_candidate.invalid"))
            return
        comparison = self.comparison
        counts = {key: sum(point.status == key for point in comparison.points) for key in
                  ("missing", "invalid", "coil_bind", "uncompressed", "reserve_short", "clear")}
        lines = [tr("spring_candidate.counts", total=len(comparison.points), **counts)]
        for key in ("invalid", "coil_bind", "uncompressed", "reserve_short"):
            first = next(((i, point) for i, point in enumerate(comparison.points, 1) if point.status == key), None)
            if first:
                index, point = first
                lines.append(tr(f"spring_candidate.first.{key}", row=index, travel=f"{point.travel_mm:+.2f}"))
        lines.append(tr("spring_candidate.result_notice"))
        if self._report_factory is not None:
            try:
                self.report = self._report_factory(comparison)
                self._export.setEnabled(True)
            except (ValueError, UnicodeError) as error:
                lines.append(tr("spring_candidate.report.unavailable", reason=str(error)))
        self._result.setPlainText("\n\n".join(lines))

    def _save_report(self) -> None:
        if self.report is not None:
            save_table_dialog(self, self.report)
