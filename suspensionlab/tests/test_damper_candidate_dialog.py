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
