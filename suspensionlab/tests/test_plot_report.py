"""Отдельный CSV графиков: неокруглённые точки, пропуски и статусы."""
from __future__ import annotations

import csv
import math

import pytest

from suspensionlab.core.sweep_plot import PlotPoint
from suspensionlab.export.csv_report import CSVReport, write_csv_report
from suspensionlab.export.plot_report import plot_number, plot_report_rows
from suspensionlab.i18n import tr


def test_numeric_roundtrip_and_unavailable_values():
    for value in (0.0, -0.0, -1.2345678901234567, 1e-200, 1e200, math.pi):
        assert float(plot_number(value)) == value
    for value in (None, math.nan, math.inf, -math.inf):
        assert plot_number(value) == "—"


def test_all_points_conflicts_missing_and_untrusted_context_are_exported(tmp_path):
    points = (PlotPoint(-1, (math.pi, None), False), PlotPoint(0, (1e-9, -0.5), True),
              PlotPoint(1, (None, None), False))
    columns, rows = plot_report_rows(points, "Ход", ("Угол", "Зазор"), ("Состояние",),
                                     (("=опасная ошибка",), ("конфликт",), ("нет решения",)))
    assert columns == ("Ход", "Угол", "Зазор", tr("export.plot_conflict"), "Состояние")
    assert float(rows[0][1]) == math.pi and rows[0][2] == "—"
    assert rows[0][3] == tr("export.plot_conflict_none")
    assert rows[1][2:4] == ("-0.5", tr("export.plot_conflict_yes"))
    assert rows[2][1:4] == ("—", "—", tr("export.plot_conflict_missing"))
    target = tmp_path / "points.csv"
    write_csv_report(CSVReport((("Предупреждение", "не подтверждает безопасность"),), columns, rows), target)
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    with target.open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.reader(handle, delimiter=";"))
    assert csv_rows[3][-1] == "'=опасная ошибка"
    assert csv_rows[4][2] == "-0.5"


@pytest.mark.parametrize("points,labels,context", [
    ((), ("y",), ()),
    ((PlotPoint(1, (1,)),), (), ((),)),
    ((PlotPoint(1, (1, 2)),), ("y",), ((),)),
    ((PlotPoint(math.nan, (1,)),), ("y",), ((),)),
    ((PlotPoint(1, (1,)),), ("y",), ()),
    ((PlotPoint(1, (1,)),), ("y",), (("лишнее",),)),
])
def test_mismatched_input_is_rejected(points, labels, context):
    with pytest.raises(ValueError):
        plot_report_rows(points, "Ход", labels, (), context)


def test_empty_path_report_can_explicitly_keep_headers():
    columns, rows = plot_report_rows((), "Ход", ("Невязка",), ("Статус",), (),
                                     allow_empty=True, conflict_label="Сбой / несовпадение")
    assert columns == ("Ход", "Невязка", "Сбой / несовпадение", "Статус") and rows == ()
