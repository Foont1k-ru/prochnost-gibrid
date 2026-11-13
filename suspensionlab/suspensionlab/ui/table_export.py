"""Снимок отображаемой таблицы для экспорта без изменения проекта."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QWidget

from .. import __version__
from ..export.csv_report import CSVReport, write_csv_report
from ..i18n import tr
from .controller import AppController


def make_report(controller: AppController, kind: str, parameters: list[tuple[str, str]],
                columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...], *,
                precision_text: str | None = None, allow_empty_rows: bool = False) -> CSVReport:
    """Общий контекст проекта и заданные отображённые значения отчёта."""
    if not columns or (not rows and not allow_empty_rows) or any(len(row) != len(columns) for row in rows):
        raise ValueError(tr("export.no_results"))
    data = json.dumps(controller.project.to_dict(), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    fingerprint = hashlib.sha256(data).hexdigest()
    meta = [
        (tr("export.kind"), kind),
        (tr("export.warning"), tr("export.warning_text")),
        (tr("export.precision"), precision_text if precision_text is not None else tr("export.precision_text")),
        (tr("export.project_name"), controller.project.meta.name or tr("export.unsaved")),
        (tr("export.saved_project"), controller.project.path or tr("export.unsaved")),
        (tr("export.project_dirty"), tr("export.yes") if controller.dirty else tr("export.no")),
        (tr("export.project_hash"), fingerprint),
        (tr("export.reproducibility"), tr("export.reproducibility_text")),
        (tr("export.version"), __version__),
        (tr("export.timestamp"), datetime.now(UTC).isoformat(timespec="seconds")),
        *parameters,
    ]
    return CSVReport(tuple(meta), columns, rows)


def make_table_report(controller: AppController, table: QTableWidget, kind: str,
                      parameters: list[tuple[str, str]]) -> CSVReport:
    """Создаёт отчёт с отпечатком проекта и округлённым содержимым таблицы."""
    if table.rowCount() == 0:
        raise ValueError(tr("export.no_results"))

    def text(item: QTableWidgetItem | None) -> str:
        return item.text() if item is not None else ""

    columns = tuple(text(table.horizontalHeaderItem(i)) for i in range(table.columnCount()))
    rows = tuple(tuple(text(table.item(row, col)) for col in range(table.columnCount()))
                 for row in range(table.rowCount()))
    return make_report(controller, kind, parameters, columns, rows)


def save_table_dialog(parent: QWidget, report: CSVReport) -> None:
    """Показывает диалог сохранения; отказ пользователя не меняет проект."""
    selected, _ = QFileDialog.getSaveFileName(parent, tr("export.title"), "", tr("export.filter"))
    if not selected:
        return
    path = Path(selected)
    if path.suffix.lower() != ".csv":
        path = path.with_name(path.name + ".csv")
    try:
        write_csv_report(report, path)
    except (OSError, UnicodeError, ValueError) as error:
        QMessageBox.warning(parent, tr("export.error_title"), tr("export.error", reason=str(error)))
