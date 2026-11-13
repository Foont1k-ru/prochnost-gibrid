"""Экспорт CSV с кириллицей, безопасными текстами и защитой существующего файла."""
import csv

import pytest

from suspensionlab.export.csv_report import CSVReport, spreadsheet_safe, write_csv_report


@pytest.mark.parametrize("value", ["=HYPERLINK(1)", "+1+2", "-SUM(A1)", "@formula", "  =1+1", "\ttext", "\nfoo"])
def test_spreadsheet_formula_injection_is_escaped(value):
    assert spreadsheet_safe(value) == "'" + value


@pytest.mark.parametrize("value", ["-1.25", "+3.00", "1.23e-2", "0", "—", "обычный текст", "  -12"])
def test_numbers_and_plain_text_are_not_escaped(value):
    assert spreadsheet_safe(value) == value


def test_writes_bom_delimiter_quotes_and_metadata(tmp_path):
    target = tmp_path / "таблица.csv"
    report = CSVReport((("Ограничения", "только точки"), ("Проект", "=evil")),
                       ("Ход, мм", "Ошибка"), (("+1.0", "=опасно;\nстрока"), ("-2.0", "—")))
    assert write_csv_report(report, target) == target
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert rows == [["Ограничения", "только точки"], ["Проект", "'=evil"], [],
                    ["Ход, мм", "Ошибка"], ["+1.0", "'=опасно;\nстрока"], ["-2.0", "—"]]


def test_failed_replace_preserves_original_and_removes_temporary(tmp_path, monkeypatch):
    from suspensionlab.export import csv_report

    target = tmp_path / "table.csv"
    target.write_text("old", encoding="utf8")
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(csv_report.os, "replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        write_csv_report(CSVReport((), ("A",), (("new",),)), target)
    assert target.read_text(encoding="utf8") == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["table.csv"]


def test_bad_dimensions_do_not_touch_file(tmp_path):
    target = tmp_path / "data.csv"
    target.write_text("old", encoding="utf8")
    with pytest.raises(ValueError):
        write_csv_report(CSVReport((), ("a", "b"), (("1",),)), target)
    assert target.read_text(encoding="utf8") == "old"


def test_empty_failed_path_report_preserves_failure_metadata_and_headers(tmp_path):
    target = tmp_path / "failed.csv"
    report = CSVReport((("Итог", "НЕ ПРОЙДЕНА"), ("Причина", "=опасный текст")),
                       ("Ход, мм", "Сила, Н"), ())
    write_csv_report(report, target)
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert rows == [["Итог", "НЕ ПРОЙДЕНА"], ["Причина", "'=опасный текст"], [], ["Ход, мм", "Сила, Н"]]
