"""Снимок по точкам сохраняет статусы, пропуски и неокруглённые значения."""
import csv

import pytest

from suspensionlab.core.damper_range import compare_candidate
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.export.csv_report import CSVReport, write_csv_report
from suspensionlab.export.damper_candidate_report import candidate_report_rows
from suspensionlab.i18n import tr


def test_report_uses_candidate_status_and_raw_values_with_missing_and_stop(tmp_path):
    result = compare_candidate([(-2, 199.9999999), (-1, 205), (0, None), (1, 250), (2, 300)],
                               StrokeLimits(200, 300), 10)
    assert [point.status for point in result.points] == ["stop", "reserve_short", "missing", "clear", "stop"]
    states = ("=опасный текст", "не проверено", "ошибка", "исходный конфликт", "—")
    columns, rows = candidate_report_rows(result, states)
    assert len(rows) == 5 and all(len(row) == 8 for row in rows)
    assert rows[0][2] == repr(199.9999999) and float(rows[0][3]) < 0
    assert rows[1][5] == tr("damper_candidate.report.status.reserve_short")
    assert rows[2][2:5] == ("—", "—", "—") and rows[2][5] == tr("damper_candidate.report.status.missing")
    assert rows[3][5] == tr("damper_candidate.report.status.clear") and rows[3][-1] == "исходный конфликт"
    assert rows[4][5] == tr("damper_candidate.report.status.stop") and rows[4][6] != "—"
    target = write_csv_report(CSVReport((("Метка", "=formula"),), columns, rows), tmp_path / "данные.csv")
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    with target.open(encoding="utf-8-sig", newline="") as stream:
        csv_rows = list(csv.reader(stream, delimiter=";"))
    assert csv_rows[0] == ["Метка", "'=formula"] and csv_rows[3][-1] == "'=опасный текст"


def test_report_rejects_incomplete_context():
    result = compare_candidate([(0, None)], StrokeLimits(200, 300), 0)
    with pytest.raises(ValueError):
        candidate_report_rows(result, ())
    result = compare_candidate([], StrokeLimits(200, 300), 0)
    with pytest.raises(ValueError):
        candidate_report_rows(result, ())
