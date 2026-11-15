"""График — дискретные точки, исходные границы и отсутствующие строки."""
import pytest
from PySide6.QtCore import Qt

from suspensionlab.core.spring_candidate import SpringCandidate, compare_spring_candidate
from suspensionlab.export.csv_report import CSVReport
from suspensionlab.export.spring_candidate_report import spring_candidate_report_rows
from suspensionlab.ui.canvas.spring_candidate_plot import SpringCandidatePlot
from suspensionlab.ui.spring_candidate_points_dialog import SpringCandidatePointsDialog


def test_plot_discrete_status_missing_and_click_selection(qtbot):
    source = ((-20., 100.), (0., None), (20., 300.))
    comparison = compare_spring_candidate(source, 200, SpringCandidate(300, 200, 100, 10, 10))
    columns, rows = spring_candidate_report_rows(comparison, source, ("исходное",) * 3)
    dialog = SpringCandidatePointsDialog(comparison, CSVReport((), columns, rows))
    qtbot.addWidget(dialog)
    dialog.resize(900, 650)
    dialog.show()
    dialog._filter.setCurrentIndex(dialog._filter.findData("coil_bind"))
    dialog._tabs.setCurrentIndex(1)
    plot = dialog._plot
    geometry = plot._geometry()
    assert geometry is not None and not plot.grab().isNull()
    for row in (1, 2, 0):
        x = plot._screen(comparison.points[row].travel_mm, geometry[3], geometry).x()
        pos = plot._screen(comparison.points[row].travel_mm, (geometry[3] + geometry[4]) / 2, geometry).toPoint()
        assert abs(pos.x() - x) < 1
        qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=pos)
        assert dialog._table.currentRow() == row and plot.row == row
        assert dialog._filter.currentData() == "all"
        assert f"Строка {row + 1}" in dialog._plot_selection.text()
    assert dialog._choose.isEnabled()


@pytest.mark.parametrize("source, candidate, notice", [
    (((0., None),), SpringCandidate(300, 200, 100, 0, 0), None),
    (((0., 200.),), SpringCandidate(300, 200, 100, 120, 90), "пересекаются"),
    (((0., 200.),), SpringCandidate(300, 200, 100, 100, 100), "совпадают"),
    (((0., 1.), (1., 200.)), SpringCandidate(300, 50, 100, 0, 0), None),
])
def test_plot_empty_single_crossed_and_invalid(qtbot, source, candidate, notice):
    from PySide6.QtWidgets import QLabel

    comparison = compare_spring_candidate(source, 200, candidate)
    plot = SpringCandidatePlot(comparison)
    qtbot.addWidget(plot)
    plot.resize(500, 300)
    plot.show()
    assert not plot.grab().isNull()
    assert (plot._geometry() is None) == all(p.length_mm is None for p in comparison.points)
    if notice:
        cols, rows = spring_candidate_report_rows(comparison, source, ("",) * len(source))
        dialog = SpringCandidatePointsDialog(comparison, CSVReport((), cols, rows))
        qtbot.addWidget(dialog)
        assert any(notice in label.text() for label in dialog.findChildren(QLabel))


def test_force_plot_selection_missing_zero_and_synchronization(qtbot):
    source = ((-30., 100.), (-20., None), (-10., 105.), (0., 200.), (10., 300.), (20., 320.))
    comparison = compare_spring_candidate(source, 200, SpringCandidate(300, 200, 100, 10, 10, 20))
    cols, rows = spring_candidate_report_rows(comparison, source, ("",) * len(source))
    dialog = SpringCandidatePointsDialog(comparison, CSVReport((), cols, rows))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._tabs.setCurrentIndex(2)
    plot = dialog._force_plot
    assert [plot._value(p) for p in comparison.points] == [None, None, 3900., 2000., 0., 0.]
    geometry = plot._geometry()
    assert geometry is not None and not plot.grab().isNull()
    dialog._filter.setCurrentIndex(dialog._filter.findData("clear"))
    for row, text in [(0, "Смыкание"), (1, "Нет исходной длины"), (2, "3900.000"), (4, "0.000")]:
        pos = plot._screen(comparison.points[row].travel_mm, (geometry[3] + geometry[4]) / 2, geometry).toPoint()
        qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=pos)
        assert dialog._table.currentRow() == row
        assert plot.row == dialog._plot.row == row
        assert text in dialog._force_selection.text()
    assert dialog._filter.currentData() == "all"
    chosen = []
    dialog.rowSelected.connect(chosen.append)
    dialog._choose.click()
    assert chosen == [4]


@pytest.mark.parametrize("rate,source", [(None, ((0, 200.),)), (10, ((0, None), (1, 100.)))])
def test_force_plot_no_values(qtbot, rate, source):
    comparison = compare_spring_candidate(source, 200, SpringCandidate(300, 200, 100, 0, 0, rate))
    plot = SpringCandidatePlot(comparison, force=True)
    qtbot.addWidget(plot)
    plot.show()
    assert plot._geometry() is None
    assert not plot.grab().isNull()


def test_force_plot_excludes_out_of_scale_without_turning_it_to_zero(qtbot):
    candidate = SpringCandidate(1e101, 2e100, 1, 0, 0, 1)
    comparison = compare_spring_candidate(((0, 2e100), (1, 1e101)), 2e100, candidate)
    assert comparison.points[0].force_n is not None and comparison.points[0].force_n > 1e100
    assert comparison.points[1].force_n == 0
    plot = SpringCandidatePlot(comparison, force=True)
    qtbot.addWidget(plot)
    plot.show()
    assert plot._geometry() is not None and not plot.grab().isNull()
