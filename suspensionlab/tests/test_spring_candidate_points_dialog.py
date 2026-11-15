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
