"""Фильтр точек не путает исходные строки и не использует округлённые числа."""
from suspensionlab.core.damper_range import compare_candidate
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.export.damper_candidate_report import candidate_report_rows
from suspensionlab.i18n import tr
from suspensionlab.ui.damper_candidate_dialog import DamperCandidateDialog


def test_filter_and_navigation_use_original_rows_and_status(qtbot):
    result = compare_candidate([(-3, 199.9999), (-2, 205), (-1, None), (0, 250), (1, 300)],
                               StrokeLimits(200, 300), 10)
    columns, rows = candidate_report_rows(result, ("источник",) * 5)
    dialog = DamperCandidateDialog(result, columns, rows, "контекст")
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._count.text() == "Строк: 5 из 5"
    assert dialog._table.item(0, 3).text() == "-0.000"
    assert dialog._table.item(0, 5).text() == tr("damper_candidate.report.status.stop")
    assert float(dialog._table.item(0, 3).toolTip()) < 0
    assert not dialog._choose.isEnabled()
    dialog._filter.setCurrentIndex(dialog._filter.findData("reserve_short"))
    assert [i for i in range(5) if not dialog._table.isRowHidden(i)] == [1]
    assert dialog._count.text() == "Строк: 1 из 5"
    dialog._table.setCurrentCell(1, 0)
    assert dialog._choose.isEnabled()
    dialog._filter.setCurrentIndex(dialog._filter.findData("missing"))
    assert [i for i in range(5) if not dialog._table.isRowHidden(i)] == [2]
    assert not dialog._choose.isEnabled()
    selected = []
    dialog.rowSelected.connect(selected.append)
    dialog._table.setCurrentCell(2, 0)
    dialog._choose.click()
    assert selected == [2]


def test_filter_with_no_matches_cannot_select_hidden_row(qtbot):
    result = compare_candidate([(0, 250)], StrokeLimits(200, 300), 10)
    columns, rows = candidate_report_rows(result, ("источник",))
    dialog = DamperCandidateDialog(result, columns, rows, "контекст")
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._table.setCurrentCell(0, 0)
    dialog._filter.setCurrentIndex(dialog._filter.findData("stop"))
    assert dialog._count.text() == "Строк: 0 из 1" and not dialog._choose.isEnabled()
    chosen = []
    dialog.rowSelected.connect(chosen.append)
    dialog._choose_row()
    assert not chosen


def test_graph_point_selection_resets_filter_without_changing_source_indices(qtbot):
    from PySide6.QtCore import QPointF, Qt

    result = compare_candidate([(-2, 199.9999), (-1, 205), (0, None), (1, 250), (2, 300)],
                               StrokeLimits(200, 300), 10)
    columns, rows = candidate_report_rows(result, ("источник",) * 5)
    dialog = DamperCandidateDialog(result, columns, rows, "контекст")
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._filter.setCurrentIndex(dialog._filter.findData("stop"))
    dialog._tabs.setCurrentIndex(1)
    plot = dialog._plot
    assert not plot.grab().isNull()
    geometry = plot._geometry()
    assert geometry is not None and geometry[3] < 200 and geometry[4] > 300
    p = plot._screen(0, 250, geometry)
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=QPointF(p.x(), p.y()).toPoint())
    assert dialog._filter.currentData() == "all" and dialog._table.currentRow() == 2
    assert plot.row == 2 and "Нет данных" in dialog._plot_selection.text()
    assert dialog._choose.isEnabled()
    selected = []
    dialog.rowSelected.connect(selected.append)
    dialog._choose.click()
    assert selected == [2]


def test_graph_handles_crossed_reference_lines_and_absent_values(qtbot):
    from PySide6.QtWidgets import QLabel

    from suspensionlab.ui.canvas.damper_candidate_plot import DamperCandidatePlot

    empty = compare_candidate([(0, None)], StrokeLimits(200, 300), 0)
    plot = DamperCandidatePlot(empty)
    qtbot.addWidget(plot)
    plot.show()
    assert plot._geometry() is None and not plot.grab().isNull()
    crossed = compare_candidate([(0, 250)], StrokeLimits(200, 300), 60)
    columns, rows = candidate_report_rows(crossed, ("источник",))
    dialog = DamperCandidateDialog(crossed, columns, rows, "контекст")
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._tabs.setCurrentIndex(1)
    assert dialog._plot.comparison.points[0].status == "reserve_short"
    assert not dialog._plot.grab().isNull()
    assert any("пересеклись" in label.text() for label in dialog.findChildren(QLabel))
    touching = compare_candidate([(0, 250)], StrokeLimits(200, 300), 50)
    cols, rows = candidate_report_rows(touching, ("источник",))
    other = DamperCandidateDialog(touching, cols, rows, "контекст")
    qtbot.addWidget(other)
    assert touching.points[0].status == "clear"
    assert any("совпали" in label.text() for label in other.findChildren(QLabel))
