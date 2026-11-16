import csv
from dataclasses import replace

from suspensionlab.core.axis_alignment import compare_pose_axes
from suspensionlab.export.csv_report import write_csv_report
from suspensionlab.i18n import tr
from suspensionlab.ui.analysis_dialog import AnalysisDialog
from suspensionlab.ui.controller import AppController


def make_analysis(qtbot):
    controller = AppController()
    controller.new_project("ring")
    dialog = AnalysisDialog(controller)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(-2)
    dialog._to.setValue(2)
    dialog._step.setValue(1)
    return controller, dialog


def test_real_sweep_dialog_export_navigation_and_invalidation(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui import axis_alignment_dialog

    controller, dialog = make_analysis(qtbot)
    original = controller.project.to_dict()
    dialog._run.click()
    assert not dialog._axis_compare_button.isEnabled()
    dialog._spring.setChecked(True)
    dialog._spring_length.setValue(320)
    dialog._run.click()
    assert not dialog._axis_compare_button.isEnabled()
    dialog._damper.setChecked(True)
    dialog._run.click()
    assert dialog._axis_compare_button.isEnabled()
    assert len(dialog._frames) == dialog._table.rowCount() == 5
    dialog._open_axis_alignment()
    view = dialog._axis_dialog
    assert view is not None and view._table.rowCount() == 5
    assert "бесконечной прямой" in tr("axis_alignment.notice")
    expected = compare_pose_axes(dialog._plot.points[0].travel_mm, dialog._frames[0])
    assert expected.result is not None
    assert float(view._report.rows[0][2]) == expected.result.angle_deg
    assert float(view._report.rows[0][3]) == expected.result.lower_offset_mm
    assert float(view._report.rows[0][5]) == expected.result.lower_pair_distance_mm
    assert float(view._report.rows[0][6]) == expected.result.upper_pair_distance_mm
    assert float(view._report.rows[0][7]) == expected.result.lower_axial_mm
    assert float(view._report.rows[0][8]) == expected.result.upper_axial_mm
    assert view._table.columnCount() == 15
    assert view._report.rows[0][10] == dialog._table.item(0, 8).text()
    assert tr("axis_alignment.notice") == dict(view._report.metadata)[tr("axis_alignment.scope_label")]
    saved = []
    monkeypatch.setattr(axis_alignment_dialog, "save_table_dialog", lambda _parent, report: saved.append(report))
    view._export.click()
    assert saved == [view._report]
    path = write_csv_report(view._report, tmp_path / "alignment.csv")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        csvrows = list(csv.reader(stream, delimiter=";"))
    assert list(view._report.columns) in csvrows and list(view._report.rows[0]) in csvrows
    assert controller.project.to_dict() == original
    view._table.setCurrentCell(4, 0)
    view._choose.click()
    assert dialog._table.currentRow() == 4 and dialog._axis_dialog is None
    dialog._open_axis_alignment()
    stale = dialog._axis_dialog
    assert stale is not None
    dialog._step.setValue(2)
    assert dialog._axis_dialog is None and not stale.isVisible() and not dialog._axis_compare_button.isEnabled()
    assert controller.project.to_dict() == original


def test_unavailable_and_conflicting_rows_are_retained(qtbot):
    _, dialog = make_analysis(qtbot)
    dialog._spring.setChecked(True)
    dialog._spring_length.setValue(320)
    dialog._damper.setChecked(True)
    dialog._run.click()
    assert dialog._frames[1] is not None and dialog._frames[2] is not None
    dialog._frames[0] = None
    dialog._frames[1] = replace(dialog._frames[1], spring=None)
    dialog._frames[2] = replace(dialog._frames[2], damper=(dialog._frames[2].center, dialog._frames[2].center))
    dialog._table.item(3, 8).setText("диагностический конфликт")
    dialog._open_axis_alignment()
    view = dialog._axis_dialog
    assert view is not None
    assert [row[9] for row in view._report.rows[:3]] == [tr("axis_alignment.status.missing_pose"),
            tr("axis_alignment.status.missing_mounts"), tr("axis_alignment.status.invalid_geometry")]
    assert all(row[2:5] == ("—", "—", "—") for row in view._report.rows[:3])
    assert all(row[5:9] == ("—", "—", "—", "—") for row in view._report.rows[:3])
    assert view._report.rows[3][10] == "диагностический конфликт"
    assert "2 из 5" in view._count.text()
    view._table.setCurrentCell(0, 0)
    view._choose.click()
    assert dialog._table.currentRow() == 0


def test_result_changes_or_project_changes_close_dialog(qtbot):
    controller, dialog = make_analysis(qtbot)
    dialog._spring.setChecked(True)
    dialog._spring_length.setValue(320)
    dialog._damper.setChecked(True)
    dialog._run.click()
    dialog._open_axis_alignment()
    assert dialog._axis_dialog is not None
    dialog._run.click()
    assert dialog._axis_dialog is None
    dialog._open_axis_alignment()
    assert dialog._axis_dialog is not None
    controller.new_project("ring")
    assert dialog._axis_dialog is None and not dialog._axis_compare_button.isEnabled()


def test_limits_graph_filters_extrema_and_full_csv(qtbot, tmp_path):
    from suspensionlab.core.axis_alignment import AxisAlignmentRow, compare_mount_axes
    from suspensionlab.export.axis_alignment import axis_alignment_rows
    from suspensionlab.export.csv_report import CSVReport
    from suspensionlab.ui.axis_alignment_dialog import AxisAlignmentDialog

    damper = ((0., 0., 0.), (0., 0., 10.))
    aligned = compare_mount_axes(((0., 0., 20.), (0., 0., 30.)), damper)
    crossing = compare_mount_axes(((0., 0., 0.), (10., 0., 0.)), damper)
    rows = (AxisAlignmentRow(0., aligned, "available"), AxisAlignmentRow(1., crossing, "available"),
            AxisAlignmentRow(2., crossing, "available"), AxisAlignmentRow(3., None, "missing_pose"))
    columns, data = axis_alignment_rows(rows, ("clear", "conflict", "clear", "missing"))
    base = CSVReport((("context", "test"),), columns, data)
    view = AxisAlignmentDialog(rows, base, source_conflicts=(False, True, False, False))
    qtbot.addWidget(view)
    view.show()
    assert view._report is not None
    assert [row[14] for row in view._report.rows] == [tr("axis_alignment.limits.combined.unchecked")] * 3 + [tr("axis_alignment.limits.combined.missing")]
    view._limit_fields["angle"].setText("0")
    assert view._report is not None
    assert [row[14] for row in view._report.rows] == [tr("axis_alignment.limits.combined.partial"),
            tr("axis_alignment.limits.combined.exceeded"), tr("axis_alignment.limits.combined.exceeded"),
            tr("axis_alignment.limits.combined.missing")]
    view._limit_fields["lower"].setText("20")
    view._limit_fields["upper"].setText("20")
    report = view._report
    assert report is not None and report.rows[0][14] == tr("axis_alignment.limits.combined.within")
    assert report.rows[0][11:14] == (tr("axis_alignment.limits.status.within"),) * 3
    assert dict(report.metadata)[tr("axis_alignment.limits.field.angle")] == "0.0"
    assert dict(report.metadata)[tr("axis_alignment.maximum_report.angle")] == "90.0; ход 1.0 мм; строка 2 (первая при равенстве)"
    view._filter.setCurrentIndex(view._filter.findData("exceeded"))
    assert [view._table.isRowHidden(i) for i in range(4)] == [True, False, False, True]
    assert "Показано 2 из 4" in view._visible_count.text()
    assert view._report == report and len(view._plot.points) == 4
    view._plot.rowSelected.emit(0)
    assert view._filter.currentData() == "all" and view._table.currentRow() == view._plot.row == 0
    view._filter.setCurrentIndex(view._filter.findData("within"))
    view._max_buttons["angle"].click()
    assert view._table.currentRow() == 1 and view._filter.currentData() == "all"  # first equal maximum
    assert view._tabs.currentIndex() == 0
    view._tabs.setCurrentIndex(1)
    assert view._plot._geometry() is not None and not view._plot.grab().isNull()
    assert view._plot.points[3].values == (None,) * 7
    path = write_csv_report(view._report, tmp_path / "axis-limits.csv")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        raw = list(csv.reader(stream, delimiter=";"))
    assert len([row for row in raw if len(row) == 15]) == 5  # header and all rows, not filtered
    assert view._report.rows[1][10] == "conflict"
    assert len(base.columns) == 11  # Original snapshot unchanged.
    assert view._plot.points[1].conflict and not view._plot.points[0].conflict
    for bad in ("-1", "nan", "inf", "91", "abc"):
        view._limit_fields["angle"].setText(bad)
        assert view._report is None and not view._export.isEnabled() and not view._filter.isEnabled()
        assert view._table.item(0, 11).text() == "—"
    view._limit_fields["angle"].setText("90,0")
    assert view._report is not None and view._export.isEnabled() and view._filter.isEnabled()
    assert view._report.rows[1][14] == tr("axis_alignment.limits.combined.within")


def test_all_missing_disables_maximum_navigation_and_graph(qtbot):
    from suspensionlab.core.axis_alignment import AxisAlignmentRow
    from suspensionlab.export.axis_alignment import axis_alignment_rows
    from suspensionlab.export.csv_report import CSVReport
    from suspensionlab.ui.axis_alignment_dialog import AxisAlignmentDialog

    rows = (AxisAlignmentRow(0., None, "missing_pose"),)
    columns, data = axis_alignment_rows(rows, ("missing",))
    view = AxisAlignmentDialog(rows, CSVReport((), columns, data), source_conflicts=(False,))
    qtbot.addWidget(view)
    assert all(not button.isEnabled() for button in view._max_buttons.values())
    assert view._plot._geometry() is None
    assert view._report is not None and view._report.rows[0][14] == tr("axis_alignment.limits.combined.missing")
    assert dict(view._report.metadata)[tr("axis_alignment.maximum_report.angle")] == "нет доступных точек"


def test_graph_click_handles_filter_and_source_conflicts(qtbot):
    from PySide6.QtCore import Qt

    from suspensionlab.core.axis_alignment import AxisAlignmentRow, compare_mount_axes
    from suspensionlab.core.sweep_plot import plot_segments
    from suspensionlab.export.axis_alignment import axis_alignment_rows
    from suspensionlab.export.csv_report import CSVReport
    from suspensionlab.ui.axis_alignment_dialog import AXIS_METRICS, AxisAlignmentDialog

    damper = ((0., 0., 0.), (0., 0., 10.))
    a = compare_mount_axes(((0., 0., 1.), (0., 0., 11.)), damper)
    b = compare_mount_axes(((0., 0., 0.), (10., 0., 0.)), damper)
    rows = (AxisAlignmentRow(0., a, "available"), AxisAlignmentRow(1., b, "available"),
            AxisAlignmentRow(2., a, "available"))
    columns, data = axis_alignment_rows(rows, ("ok", "исходный конфликт", "ok"))
    view = AxisAlignmentDialog(rows, CSVReport((), columns, data), source_conflicts=(False, True, False))
    qtbot.addWidget(view)
    view.show()
    view._limit_fields["angle"].setText("1")
    view._filter.setCurrentIndex(view._filter.findData("exceeded"))
    assert view._table.isRowHidden(0) and not view._table.isRowHidden(1)
    assert plot_segments(view._plot.points, 0, len(AXIS_METRICS)) == ()
    view._tabs.setCurrentIndex(1)
    qtbot.waitExposed(view)
    geometry = view._plot._geometry()
    assert geometry is not None
    click = view._plot._screen(0., 0., geometry).toPoint()
    qtbot.mouseClick(view._plot, Qt.MouseButton.LeftButton, pos=click)
    assert view._filter.currentData() == "all" and view._plot.row == view._table.currentRow() == 0
    for index in range(len(AXIS_METRICS)):
        view._metric.setCurrentIndex(index)
        assert view._plot._geometry() is not None
    view._plot.rowSelected.emit(1)
    assert view._plot.points[1].conflict and "конфликт" in view._plot_selection.text().lower()


def test_conflict_flags_must_match_source_rows(qtbot):
    import pytest

    from suspensionlab.core.axis_alignment import AxisAlignmentRow
    from suspensionlab.export.axis_alignment import axis_alignment_rows
    from suspensionlab.export.csv_report import CSVReport
    from suspensionlab.ui.axis_alignment_dialog import AxisAlignmentDialog

    rows = (AxisAlignmentRow(0., None, "missing_pose"),)
    columns, data = axis_alignment_rows(rows, ("missing",))
    with pytest.raises(ValueError):
        AxisAlignmentDialog(rows, CSVReport((), columns, data), source_conflicts=())
