"""Атомарный экспорт отображаемой таблицы с защитой текстовых ячеек от формул."""
from __future__ import annotations

import csv
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

# В виде числа не допускаются формулы вида +1+2; научная запись разрешена.
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


def spreadsheet_safe(value: str) -> str:
    """Сохраняет числа числами; потенциальные формулы помещает в текст."""
    stripped = value.lstrip(" \t\r\n\ufeff")
    if stripped and stripped[0] in "=+-@" and not _NUMBER.fullmatch(stripped):
        return "'" + value
    # Табуляция и перевод строки могут использоваться как префикс формулы.
    if value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


@dataclass(frozen=True)
class CSVReport:
    """Заголовки и значения в той же округлённой форме, что видит пользователь."""

    metadata: tuple[tuple[str, str], ...]
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def write_csv_report(report: CSVReport, target: str | Path) -> Path:
    """Записывает UTF-8 с BOM и разделителем `;`, заменяя файл после успеха.

    Не создаёт родительские каталоги; при сбое временный файл удаляется,
    существующий файл остаётся нетронутым до успешного os.replace.
    """
    if not report.columns or any(len(row) != len(report.columns) for row in report.rows):
        raise ValueError("Несогласованные колонки отчёта")
    path = Path(target)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=path.parent,
                                         prefix=".suspensionlab-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            writer = csv.writer(handle, delimiter=";", lineterminator="\r\n")
            for name, value in report.metadata:
                writer.writerow([spreadsheet_safe(name), spreadsheet_safe(value)])
            writer.writerow([])
            writer.writerow([spreadsheet_safe(value) for value in report.columns])
            for row in report.rows:
                writer.writerow([spreadsheet_safe(value) for value in row])
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
    return path
