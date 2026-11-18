"""Экспорт кандидата пружины включает пропуски, конфликт и контекст строки."""
import csv
from dataclasses import replace

import pytest

from suspensionlab.core.spring_candidate import SpringCandidate, compare_spring_candidate
from suspensionlab.export.csv_report import CSVReport, write_csv_report
from suspensionlab.export.spring_candidate_report import spring_candidate_report_rows
from suspensionlab.i18n import tr


def test_report_preserves_precision_signed_values_and_source_states(tmp_path):
    source = ((-1.25, 110.1234567890123), (0, None), (1, 310.0), (2, 1.0))
    result = compare_spring_candidate(source, 200, SpringCandidate(300, 190, 100, 5, 5))
    cols, rows = spring_candidate_report_rows(result, source, ("=формула", "ошибка", "упор", "нет"))
    assert len(cols) == 10 and len(rows) == 4
    assert float(rows[0][2]) == source[0][1]
    assert float(rows[0][3]) == result.points[0].length_mm
    assert float(rows[0][4]) == result.points[0].coil_clearance_mm
    assert rows[1][2:6] == ("—", "—", "—", "—")
    assert rows[1][6] == tr("spring_candidate.report.status.missing")
    assert rows[2][6] == tr("spring_candidate.report.status.uncompressed")
    assert rows[3][6] == tr("spring_candidate.report.status.invalid")
    assert float(rows[3][3]) < 0 and rows[2][7] == "упор"
    path = write_csv_report(CSVReport((("Контекст", "=X"),), cols, rows), tmp_path / "comparison.csv")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        data = list(csv.reader(handle, delimiter=";"))
    assert data[0][1] == "'=X" and data[3][7] == "'=формула"


def test_report_rejects_misaligned_data():
    source = ((0, 200.), (1, None))
    result = compare_spring_candidate(source, 200, SpringCandidate(300, 200, 100, 0, 0))
    for bad_source, states in ((source[:-1], ("", "")), (source, ("",)), (((2, 200.), (1, None)), ("", "")),
                               (((0, 201.), (1, None)), ("", ""))):
        with pytest.raises(ValueError):
            spring_candidate_report_rows(result, bad_source, states)
    with pytest.raises(ValueError):
        spring_candidate_report_rows(replace(result, points=()), (), ())


def test_optional_force_csv_reason_and_zero(tmp_path):
    source = ((0., 100.), (1., None), (2., 200.), (3., 300.))
    candidate = SpringCandidate(300, 200, 100, 0, 0, linear_rate_n_mm=5)
    result = compare_spring_candidate(source, 200, candidate)
    columns, rows = spring_candidate_report_rows(result, source, ("",) * len(source))
    assert [row[8] for row in rows] == ["—", "—", "500.0", "0.0"]
    assert [row[9] for row in rows] == [tr("spring_candidate.force.status.coil_bind"),
                                        tr("spring_candidate.force.status.missing"),
                                        tr("spring_candidate.force.status.calculated"),
                                        tr("spring_candidate.force.status.calculated")]
    path = write_csv_report(CSVReport((), columns, rows), tmp_path / "force.csv")
    with path.open(encoding="utf-8-sig", newline="") as file:
        data = list(csv.reader(file, delimiter=";"))
    assert data[-1][8] == "0.0" and data[-2][8] == "500.0" and data[-3][8] == "—"
