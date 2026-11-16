"""Категории фильтра не скрывают или не переставляют исходные строки."""
from suspensionlab.core.spring_candidate import SpringCandidate, compare_spring_candidate
from suspensionlab.export.csv_report import CSVReport
from suspensionlab.export.spring_candidate_report import spring_candidate_report_rows
from suspensionlab.ui.spring_candidate_points_dialog import SpringCandidatePointsDialog


def test_all_status_filters_and_missing_navigation(qtbot):
    source = ((0, None), (1, 1.), (2, 150.), (3, 350.), (4, 155.), (5, 250.))
    comparison = compare_spring_candidate(source, 200, SpringCandidate(300, 150, 100, 10, 10))
    assert [point.status for point in comparison.points] == ["missing", "invalid", "coil_bind", "uncompressed", "reserve_short", "clear"]
    columns, rows = spring_candidate_report_rows(comparison, source, ("—",) * 6)
    report = CSVReport((), columns, rows)
    dialog = SpringCandidatePointsDialog(comparison, report)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._table.horizontalHeader().logicalIndex(2) == 6
    for index, point in enumerate(comparison.points):
        dialog._filter.setCurrentIndex(dialog._filter.findData(point.status))
        assert [not dialog._table.isRowHidden(i) for i in range(6)] == [i == index for i in range(6)]
        assert "1 из 6" in dialog._count.text()
        dialog._table.setCurrentCell(index, 0)
        assert dialog._choose.isEnabled()
    dialog._filter.setCurrentIndex(dialog._filter.findData("all"))
    assert not dialog._choose.isEnabled() and "6 из 6" in dialog._count.text()
    dialog._table.setCurrentCell(0, 0)
    chosen = []
    dialog.rowSelected.connect(chosen.append)
    dialog._choose.click()
    assert chosen == [0]


def test_force_filter_combines_with_geometry_and_keeps_report_and_graphs(qtbot, tmp_path):
    from suspensionlab.export.csv_report import write_csv_report
    source = ((0, None), (1, 1.), (2, 150.), (3, 350.), (4, 155.), (5, 250.), (6, 349.9999))
    comparison = compare_spring_candidate(source, 200, SpringCandidate(300, 150, 100, 10, 10, 1))
    columns, rows = spring_candidate_report_rows(comparison, source, ("—",) * len(source))
    report = CSVReport((), columns, rows)
    dialog = SpringCandidatePointsDialog(comparison, report)
    before = write_csv_report(report, tmp_path / "before.csv").read_bytes()
    qtbot.addWidget(dialog)
    dialog.show()
    expected = {
        "all": [0, 1, 2, 3, 4, 5, 6], "calculated": [3, 4, 5, 6], "positive": [4, 5, 6],
        "zero": [3], "unavailable": [0, 1, 2], "missing": [0], "invalid": [1], "coil_bind": [2],
        "overflow": [], "disabled": [],
    }
    for key, selected in expected.items():
        dialog._force_filter.setCurrentIndex(dialog._force_filter.findData(key))
        assert [i for i in range(len(source)) if not dialog._table.isRowHidden(i)] == selected
        assert f"{len(selected)} из 7" in dialog._count.text()
    # Сила 0.0001 отображается округлённой до 0.000, но фильтруется без округления.
    assert dialog._table.item(6, 8).text() == "0.000"
    dialog._force_filter.setCurrentIndex(dialog._force_filter.findData("positive"))
    dialog._filter.setCurrentIndex(dialog._filter.findData("reserve_short"))
    assert [i for i in range(len(source)) if not dialog._table.isRowHidden(i)] == [4, 6]
    assert dialog._force_plot.comparison is comparison and report.rows == rows
    dialog._table.setCurrentCell(4, 0)
    assert dialog._choose.isEnabled()
    dialog._force_filter.setCurrentIndex(dialog._force_filter.findData("zero"))
    assert "0 из 7" in dialog._count.text() and not dialog._choose.isEnabled()
    assert report.rows == rows
    assert write_csv_report(report, tmp_path / "after.csv").read_bytes() == before


def test_force_filter_disabled_overflow_and_graph_selection(qtbot):
    source = ((0, 2.), (1, None), (2, 1e308))
    candidate = SpringCandidate(1e308, 2, 1, 0, 0, 1e308)
    comparison = compare_spring_candidate(source, 2, candidate)
    columns, rows = spring_candidate_report_rows(comparison, source, ("",) * len(source))
    dialog = SpringCandidatePointsDialog(comparison, CSVReport((), columns, rows))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._force_filter.setCurrentIndex(dialog._force_filter.findData("overflow"))
    assert [i for i in range(3) if not dialog._table.isRowHidden(i)] == [0]
    dialog._filter.setCurrentIndex(dialog._filter.findData("missing"))
    assert "0 из 3" in dialog._count.text()
    # Выбор точки на графике сбрасывает только несовместимые фильтры.
    dialog._select_plot_row(1)
    assert dialog._filter.currentData() == "missing" and dialog._force_filter.currentData() == "all"
    assert dialog._table.currentRow() == 1 and dialog._choose.isEnabled()
    dialog._force_filter.setCurrentIndex(dialog._force_filter.findData("calculated"))
    dialog._select_plot_row(0)
    assert dialog._filter.currentData() == "all" and dialog._force_filter.currentData() == "all"
    assert dialog._table.currentRow() == 0

    disabled = compare_spring_candidate(((0, 200.), (1, None)), 200, SpringCandidate(300, 200, 100, 0, 0))
    cols, rows = spring_candidate_report_rows(disabled, ((0, 200.), (1, None)), ("", ""))
    other = SpringCandidatePointsDialog(disabled, CSVReport((), cols, rows))
    qtbot.addWidget(other)
    other._force_filter.setCurrentIndex(other._force_filter.findData("disabled"))
    assert "2 из 2" in other._count.text()
    other._force_filter.setCurrentIndex(other._force_filter.findData("zero"))
    assert "0 из 2" in other._count.text()
