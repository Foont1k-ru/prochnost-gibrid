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
    assert view._report.rows[0][6] == dialog._table.item(0, 8).text()
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
    assert [row[5] for row in view._report.rows[:3]] == [tr("axis_alignment.status.missing_pose"),
            tr("axis_alignment.status.missing_mounts"), tr("axis_alignment.status.invalid_geometry")]
    assert all(row[2:5] == ("—", "—", "—") for row in view._report.rows[:3])
    assert view._report.rows[3][6] == "диагностический конфликт"
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
