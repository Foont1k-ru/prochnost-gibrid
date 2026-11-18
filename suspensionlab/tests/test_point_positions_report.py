"""Координатный CSV не теряет ошибки и не выдумывает положения."""
import csv
from math import inf, nan

import pytest

from suspensionlab.core.scene3d import Scene3D
from suspensionlab.export.csv_report import CSVReport, write_csv_report
from suspensionlab.export.point_positions_report import point_position_rows
from suspensionlab.i18n import tr


def test_point_rows_precision_missing_status_and_csv_safety(tmp_path):
    code = "ubj"
    first = Scene3D(-0.123456789012345, (), ((code, (1.000000000123, -2.3, 0.0)),))
    missing_point = Scene3D(1, (), ())
    columns, rows = point_position_rows(code, (first.travel_mm, 0, 1), (first, None, missing_point),
                                         ("=опасная формула", "Ошибка", "На упоре"))
    assert len(columns) == 7 and len(rows) == 3
    assert rows[0][:5] == ("1", repr(first.travel_mm), repr(1.000000000123), "-2.3", "0.0")
    assert rows[0][5] == tr("analysis.scene3d.point_report.availability.available")
    assert rows[1][2:5] == ("—", "—", "—")
    assert rows[1][5] == tr("analysis.scene3d.point_report.availability.frame_missing")
    assert rows[2][2:5] == ("—", "—", "—")
    assert rows[2][5] == tr("analysis.scene3d.point_report.availability.point_missing")
    assert rows[2][6] == "На упоре"
    path = write_csv_report(CSVReport((("Описание", "+1+2"),), columns, rows), tmp_path / "point.csv")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        data = list(csv.reader(stream, delimiter=";"))
    assert data[0][1] == "'+1+2" and data[3][6] == "'=опасная формула"
    assert float(data[3][2]) == 1.000000000123


@pytest.mark.parametrize("code, travels, scenes, states", [
    ("unknown", (0,), (None,), ("",)),
    ("ubj", (), (), ()),
    ("ubj", (0, 1), (None,), ("", "")),
    ("ubj", (0,), (None,), ()),
    ("ubj", (nan,), (None,), ("",)),
    ("ubj", (0,), (Scene3D(1, (), ()),), ("",)),
    ("ubj", (0,), (Scene3D(0, (), (("ubj", (inf, 0, 0)),)),), ("",)),
])
def test_point_rows_reject_invalid_or_inconsistent_inputs(code, travels, scenes, states):
    with pytest.raises(ValueError):
        point_position_rows(code, travels, scenes, states)
