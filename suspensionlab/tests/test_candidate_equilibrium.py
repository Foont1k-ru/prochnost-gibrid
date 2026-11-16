"""Связь линейного кандидата и условного баланса без изменения проекта."""
import pytest

from suspensionlab.core.equilibrium import SpringEquilibrium
from suspensionlab.core.spring_candidate import SpringCandidate
from suspensionlab.core.spring_characteristics import SpringCharacteristic
from suspensionlab.model.templates import load_template


def test_override_characteristic_drives_candidate_force_and_balance():
    project = load_template("ring")
    original = project.to_dict()
    candidate = SpringCandidate(350, 230, 150, 10, 5, 12.5)
    characteristic = SpringCharacteristic(candidate.free_mm, candidate.linear_rate_n_mm, coil_bind_length_mm=150)
    model = SpringEquilibrium(project.front, candidate.installed_mm, coil_bind_length_mm=150,
                              spring_characteristic=characteristic)
    sample = model.evaluate(12, 1)
    assert sample.spring.force_n == pytest.approx(12.5 * max(350 - sample.spring.length_mm, 0))
    assert sample.wheel_support_n == pytest.approx(sample.spring.force_n * sample.motion_ratio)
    answer = model.find(sample.wheel_support_n, -30, 30)
    assert answer.estimate.travel_mm == pytest.approx(12, abs=0.1)
    default = SpringEquilibrium(project.front, candidate.installed_mm, coil_bind_length_mm=150)
    assert default.evaluate(12, 1).spring.force_n != sample.spring.force_n
    assert project.to_dict() == original


def test_override_requires_matching_bind_and_preserves_default():
    project = load_template("ring")
    characteristic = SpringCharacteristic(350, 12.5, coil_bind_length_mm=150)
    with pytest.raises(ValueError, match="смыкания"):
        SpringEquilibrium(project.front, 230, coil_bind_length_mm=151, spring_characteristic=characteristic)
    with pytest.raises(ValueError, match="смыкания"):
        SpringEquilibrium(project.front, 230, spring_characteristic=characteristic)
    default = SpringEquilibrium(project.front, 230)
    assert default.characteristic.free_length_mm == project.front.spring.free_len_mm
    assert default.characteristic.progressive == tuple(project.front.spring.progressive)


def test_candidate_context_cannot_silently_switch_axes(qtbot):
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    controller = AppController()
    controller.new_project("ring")
    dialog = EquilibriumDialog(controller, candidate=SpringCandidate(350, 230, 150, 10, 5, 12.5),
                               initial_role="front", initial_side="left")
    qtbot.addWidget(dialog)
    dialog._load.setValue(1000)
    dialog._side.setCurrentIndex(dialog._side.findData("right"))
    dialog._run.click()
    assert dialog._result is None and "заново" in dialog._status.text()


def test_only_estimate_reserve_evaluated_and_exported(qtbot, monkeypatch):
    from suspensionlab.i18n import tr
    from suspensionlab.ui import equilibrium_dialog
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    controller = AppController()
    controller.new_project("ring")
    before = controller.project.to_dict()
    candidate = SpringCandidate(350, 230, 150, 1000, 1000, 12.5)
    characteristic = SpringCharacteristic(350, 12.5, coil_bind_length_mm=150)
    target = SpringEquilibrium(controller.project.front, 230, coil_bind_length_mm=150,
                               spring_characteristic=characteristic).evaluate(12, 1).wheel_support_n
    dialog = EquilibriumDialog(controller, candidate=candidate)
    qtbot.addWidget(dialog)
    dialog._load.setValue(target)
    dialog._run.click()
    assert dialog._result is not None and dialog._display_values is not None
    values = dialog._display_values
    assert values["candidate_coil_condition"] == "не выполнено по численному критерию"
    assert values["candidate_compression_condition"] == "не выполнено по численному критерию"
    assert values["candidate_status"] == tr("spring_candidate.report.status.reserve_short")
    assert "Только в оценке середины" in dialog._output.text()
    assert "Отдельные точки пути" in dialog._output.text()
    captured = []
    monkeypatch.setattr(equilibrium_dialog, "save_table_dialog", lambda _parent, report: captured.append(report))
    dialog._export_button.click()
    rows = dict(captured[0].rows)
    for key in ("candidate_coil", "candidate_compression", "candidate_coil_condition",
                "candidate_compression_condition", "candidate_status"):
        assert rows[tr(f"equilibrium_ui.field.{key}")] == values[key]
    assert controller.project.to_dict() == before
    dialog._load.setValue(dialog._load.value() + 10)
    assert dialog._display_values is None and not dialog._export_button.isEnabled()


def test_path_candidate_row_uses_unrounded_boundaries():
    from dataclasses import replace
    from math import inf, nextafter

    from suspensionlab.export.equilibrium_path import CANDIDATE_PATH_COLUMNS, format_candidate_path_sample

    sample = SpringEquilibrium(load_template("ring").front, 230).check_path(0, 1000).samples[0]
    candidate = SpringCandidate(300, 200, 100, 10, 10, 12.5)
    sample = replace(sample, spring=replace(sample.spring, length_mm=nextafter(110, 0)))
    row = dict(zip(CANDIDATE_PATH_COLUMNS, format_candidate_path_sample(sample, candidate), strict=True))
    assert row["candidate_coil_condition"].startswith("не выполнено")
    assert row["candidate_compression_condition"].startswith("выполнено")
    sample = replace(sample, spring=replace(sample.spring, length_mm=nextafter(290, inf)))
    row = dict(zip(CANDIDATE_PATH_COLUMNS, format_candidate_path_sample(sample, candidate), strict=True))
    assert row["candidate_compression"] == "10.0000"
    assert row["candidate_coil_condition"].startswith("выполнено")
    assert row["candidate_compression_condition"].startswith("не выполнено")


def test_candidate_path_actual_dialog_and_csv(qtbot, monkeypatch):
    from PySide6.QtCore import QTimer

    from suspensionlab.core.spring_candidate import candidate_geometry
    from suspensionlab.export.equilibrium_path import CANDIDATE_PATH_COLUMNS, PATH_COLUMNS
    from suspensionlab.i18n import tr
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    c = AppController()
    c.new_project("ring")
    before = c.project.to_dict()
    candidate = SpringCandidate(350, 230, 150, 77, 120, 12.5)
    model = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=150,
                              spring_characteristic=SpringCharacteristic(350, 12.5, coil_bind_length_mm=150))
    dialog = EquilibriumDialog(c, candidate=candidate)
    qtbot.addWidget(dialog)
    dialog._load.setValue(model.evaluate(12, 1).wheel_support_n)
    dialog._run.click()
    path = dialog._path
    assert path is not None and path.completed and dialog._result is not None
    seen = []

    def inspect():
        view = dialog._path_dialog
        assert view is not None
        qtbot.addWidget(view)
        assert view._table.columnCount() == len(PATH_COLUMNS) + len(CANDIDATE_PATH_COLUMNS)
        geoms = [candidate_geometry(candidate, s.spring.length_mm) for s in path.samples]
        assert any(g.coil_reserve_ok for g in geoms) and any(not g.coil_reserve_ok for g in geoms)
        assert f"до смыкания не выполнено в {sum(not g.coil_reserve_ok for g in geoms)}" in view._candidate_summary.text()
        from suspensionlab.export.equilibrium_path import candidate_path_summary, format_candidate_path_minima
        summary = candidate_path_summary(path, candidate)
        assert summary.minimum_coil is not None and summary.minimum_compression is not None
        minima = format_candidate_path_minima(summary)
        assert view._candidate_minima.text() == "\n".join(minima)
        view._views.setCurrentIndex(1)
        view._candidate_min_coil.click()
        assert view._views.currentIndex() == 0 and view._table.currentRow() == summary.minimum_coil.row
        assert view._plot.row == summary.minimum_coil.row
        view._candidate_min_compression.click()
        assert view._table.currentRow() == summary.minimum_compression.row
        assert view._plot.row == summary.minimum_compression.row
        table = dialog._path_report(path, view._table)
        graph = dialog._path_graph_report(path, view._table, view._plot.points, view._plot_metric.currentText())
        assert len(table.rows) == len(graph.rows) == len(path.samples)
        for i, geometry in enumerate(geoms):
            row = dict(zip(table.columns, table.rows[i], strict=True))
            column = tr("equilibrium_path.column.candidate_coil_condition")
            assert row[column] == tr("candidate_balance_reserve.ok" if geometry.coil_reserve_ok else "candidate_balance_reserve.short")
            assert dict(zip(graph.columns, graph.rows[i], strict=True))[column] == row[column]
        assert "отказ без данных" in dict(table.metadata)[tr("equilibrium_path.candidate_report_limits")]
        for report in (table, graph):
            metadata = dict(report.metadata)
            assert metadata[tr("equilibrium_path.candidate_report_coil_min")] == minima[0]
            assert metadata[tr("equilibrium_path.candidate_report_compression_min")] == minima[1]
        seen.append(True)
        view.reject()

    QTimer.singleShot(0, inspect)
    dialog._show_path()
    assert seen == [True] and c.project.to_dict() == before
    dialog._load.setValue(dialog._load.value() + 10)
    assert dialog._path is None and not dialog._path_button.isEnabled()


@pytest.mark.parametrize("empty", [False, True])
def test_candidate_failed_path_exports_only_retained_samples(qtbot, monkeypatch, empty):
    from suspensionlab.core.equilibrium import EquilibriumPathError
    from suspensionlab.export.equilibrium_path import CANDIDATE_PATH_COLUMNS, PATH_COLUMNS
    from suspensionlab.i18n import tr
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    c = AppController()
    c.new_project("ring")
    candidate = SpringCandidate(350, 230, 231 if empty else 225, 2, 1, 12.5)
    model = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=candidate.coil_bind_mm,
                              spring_characteristic=SpringCharacteristic(350, 12.5, coil_bind_length_mm=candidate.coil_bind_mm))
    path = model.check_path(30, 1000, step_mm=5)
    assert path.failure is not None and bool(path.samples) != empty
    monkeypatch.setattr(SpringEquilibrium, "find", lambda *args, **kwargs: (_ for _ in ()).throw(EquilibriumPathError(path)))
    dialog = EquilibriumDialog(c, candidate=candidate)
    qtbot.addWidget(dialog)
    dialog._load.setValue(1000)
    dialog._run.click()
    assert dialog._path is path and dialog._result is None
    view = EquilibriumPathDialog(path, dialog, candidate=candidate)
    qtbot.addWidget(view)
    report = dialog._path_report(path, view._table)
    graph = dialog._path_graph_report(path, view._table, view._plot.points, view._plot_metric.currentText())
    assert len(report.rows) == len(graph.rows) == len(path.samples)
    assert len(report.columns) == len(PATH_COLUMNS) + len(CANDIDATE_PATH_COLUMNS)
    assert "НЕ ПРОЙДЕНА" in dict(report.metadata)[tr("equilibrium_path.report_status")]
    assert f"сохранённых точек {len(path.samples)}" in view._candidate_summary.text()
    assert "отказ без данных" in view._candidate_summary.text()
    assert view._candidate_min_coil.isEnabled() == (not empty)
    assert view._candidate_min_compression.isEnabled() == (not empty)
    if empty:
        assert view._candidate_plot is not None and view._candidate_plot._geometry() is None
        assert not view._candidate_plot.grab().isNull()
        assert "минимум не определён" in view._candidate_minima.text()
        assert "минимум не определён" in dict(report.metadata)[tr("equilibrium_path.candidate_report_coil_min")]
    else:
        view._candidate_min_coil.click()
        assert view._table.currentRow() >= 0


def test_candidate_geometry_summary_extrema_are_exact_and_first_on_ties():
    from math import inf, nextafter

    from suspensionlab.core.spring_candidate import summarize_candidate_geometry

    candidate = SpringCandidate(300, 200, 100, 10, 10)
    empty = summarize_candidate_geometry(candidate, ())
    assert empty.total == empty.coil_short == empty.compression_short == 0
    assert empty.minimum_coil is empty.minimum_compression is None
    points = ((0, 110), (1, 290), (2, 110), (3, nextafter(290, inf)))
    result = summarize_candidate_geometry(candidate, points)
    assert result.total == 4 and result.coil_short == 0 and result.compression_short == 1
    assert result.minimum_coil is not None and result.minimum_coil.row == 0
    assert result.minimum_coil.value_mm == 10 and result.minimum_coil.condition_ok
    assert result.minimum_compression is not None and result.minimum_compression.row == 3
    assert not result.minimum_compression.condition_ok and result.minimum_compression.value_mm < 10
    assert summarize_candidate_geometry(candidate, ((1, 290), (2, 290))).minimum_compression.row == 0
    zero = SpringCandidate(300, 200, 100, 0, 0)
    result = summarize_candidate_geometry(zero, ((0, 100), (1, 300)))
    assert result.minimum_coil.value_mm == 0 and not result.minimum_coil.condition_ok
    assert result.minimum_compression.value_mm == 0 and not result.minimum_compression.condition_ok
    with pytest.raises(ValueError):
        summarize_candidate_geometry(candidate, ((inf, 200),))
    with pytest.raises(ValueError):
        summarize_candidate_geometry(candidate, ((0, inf),))


def test_candidate_mismatch_marks_diagnostic_extremum_and_report(qtbot, monkeypatch):
    from dataclasses import replace

    from suspensionlab.core.equilibrium import EquilibriumPathError, PathFailure
    from suspensionlab.i18n import tr
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    c = AppController()
    c.new_project("ring")
    candidate = SpringCandidate(350, 230, 150, 10, 10, 12.5)
    problem = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=150,
                                spring_characteristic=SpringCharacteristic(350, 12.5, coil_bind_length_mm=150))
    path = problem.check_path(10, 1000)
    path = replace(path, failure=PathFailure(10, 10, "branch_mismatch", "ветви не совпали"))
    monkeypatch.setattr(SpringEquilibrium, "find", lambda *args, **kwargs: (_ for _ in ()).throw(EquilibriumPathError(path)))
    dialog = EquilibriumDialog(c, candidate=candidate)
    qtbot.addWidget(dialog)
    dialog._load.setValue(1000)
    dialog._run.click()
    view = EquilibriumPathDialog(path, dialog, candidate=candidate)
    qtbot.addWidget(view)
    report = dialog._path_report(path, view._table)
    minimum = dict(report.metadata)[tr("equilibrium_path.candidate_report_coil_min")]
    assert "Конечная точка диагностическая" in minimum and minimum in view._candidate_minima.text()
    view._candidate_min_coil.click()
    assert view._table.currentRow() == len(path.samples) - 1
    assert view._candidate_plot is not None and view._candidate_plot_selection is not None
    assert view._candidate_plot.diagnostic_rows == frozenset((len(path.samples) - 1,))
    assert "Конечная точка диагностическая" in view._candidate_plot_selection.text()
    assert dialog._result is None


def test_candidate_path_plot_adapter_preserves_saved_samples_and_raw_boundaries():
    from dataclasses import replace
    from math import nextafter

    from suspensionlab.core.equilibrium import PathFailure
    from suspensionlab.export.equilibrium_path import candidate_path_comparison, candidate_path_diagnostic_row

    candidate = SpringCandidate(300, 200, 100, 10, 10, 12.5)
    path = SpringEquilibrium(load_template("ring").front, 230).check_path(2, 1000, step_mm=1)
    original = path.samples[0]
    low = replace(original, travel_mm=-3, spring=replace(original.spring, length_mm=nextafter(110, 0)))
    high = replace(original, travel_mm=4, spring=replace(original.spring, length_mm=290))
    path = replace(path, samples=(low, high), failure=PathFailure(9, 9, "kinematics", "нет данных"))
    result = candidate_path_comparison(path, candidate)
    assert result.candidate is candidate and len(result.points) == 2
    assert result.points[0].travel_mm == -3 and result.points[0].length_mm == nextafter(110, 0)
    assert result.points[0].status == "reserve_short" and result.points[1].status == "clear"
    assert candidate_path_diagnostic_row(path) is None
    mismatch = replace(path, failure=PathFailure(4, 4, "branch_mismatch", "ветвь"))
    assert candidate_path_diagnostic_row(mismatch) == 1
    empty = replace(mismatch, samples=())
    assert not candidate_path_comparison(empty, candidate).points and candidate_path_diagnostic_row(empty) is None


def test_candidate_path_plot_actual_view_click_and_csv(qtbot, monkeypatch):
    from PySide6.QtCore import Qt, QTimer

    from suspensionlab.i18n import tr
    from suspensionlab.ui import equilibrium_path_dialog
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    c = AppController()
    c.new_project("ring")
    candidate = SpringCandidate(350, 230, 150, 77, 120, 12.5)
    characteristic = SpringCharacteristic(350, 12.5, coil_bind_length_mm=150)
    model = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=150, spring_characteristic=characteristic)
    dialog = EquilibriumDialog(c, candidate=candidate)
    qtbot.addWidget(dialog)
    dialog._load.setValue(model.evaluate(12, 1).wheel_support_n)
    dialog._run.click()
    path = dialog._path
    assert path is not None and path.completed
    captured = []
    monkeypatch.setattr(equilibrium_path_dialog, "save_table_dialog", lambda parent, report: captured.append(report))
    observed = []

    def inspect():
        view = dialog._path_dialog
        assert view is not None and view._candidate_plot is not None and view._candidate_plot_selection is not None
        plot = view._candidate_plot
        view._views.setCurrentIndex(2)
        assert not plot.grab().isNull()
        geometry = plot._geometry()
        assert geometry is not None
        row = len(path.samples) - 1
        pos = plot._screen(path.samples[row].travel_mm, (geometry[3] + geometry[4]) / 2, geometry).toPoint()
        qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=pos)
        assert view._table.currentRow() == view._plot.row == plot.row == row
        assert f"Строка {row + 1}" in view._candidate_plot_selection.text()
        view._table.setCurrentCell(0, 0)
        assert plot.row == 0 and "Строка 1" in view._candidate_plot_selection.text()
        assert view._candidate_plot_export is not None and view._candidate_plot_export.isEnabled()
        view._candidate_plot_export.click()
        report = captured[0]
        assert len(report.rows) == len(path.samples)
        assert dict(report.metadata)[tr("export.plot_selected")] == tr("equilibrium_path.candidate_plot_selected")
        assert tr("equilibrium_path.column.candidate_status") in report.columns
        assert "границы" in dict(report.metadata)[tr("export.plot_selected")]
        observed.append(True)
        view.reject()

    QTimer.singleShot(0, inspect)
    dialog._show_path()
    assert observed == [True]


@pytest.mark.parametrize("reserve, expected", [(100, "совпадают"), (110, "пересекаются")])
def test_path_plot_marks_crossed_and_coincident_limits(qtbot, reserve, expected):
    from PySide6.QtWidgets import QLabel

    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    candidate = SpringCandidate(300, 200, 100, reserve, reserve, 10)
    path = SpringEquilibrium(load_template("ring").front, 230).check_path(0, 1000)
    view = EquilibriumPathDialog(path, candidate=candidate)
    qtbot.addWidget(view)
    assert any(expected in label.text() for label in view.findChildren(QLabel))
    assert view._candidate_plot is not None
    assert view._candidate_plot.comparison.points[0].length_mm == path.samples[0].spring.length_mm
    ordinary = EquilibriumPathDialog(path)
    qtbot.addWidget(ordinary)
    assert ordinary._candidate_plot is None and ordinary._views.count() == 2


def test_path_filters_combine_exact_conditions_and_reveal_selected_rows(qtbot):
    from dataclasses import replace
    from math import inf, nextafter

    from suspensionlab.core.equilibrium import PathFailure
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    candidate = SpringCandidate(300, 200, 100, 10, 10, 12.5)
    source = SpringEquilibrium(load_template("ring").front, 230).check_path(0, 1000)
    original = source.samples[0]
    lengths = (110., nextafter(110., 0), 290., nextafter(290., inf))
    samples = tuple(replace(original, travel_mm=float(i), spring=replace(original.spring, length_mm=value))
                    for i, value in enumerate(lengths))
    path = replace(source, samples=samples, failure=PathFailure(3, 3, "branch_mismatch", "ветви"))
    view = EquilibriumPathDialog(path, candidate=candidate)
    qtbot.addWidget(view)
    view.show()
    assert "Показано 4 из 4" in view._filter_count.text()
    view._coil_filter.setCurrentIndex(view._coil_filter.findData("short"))
    assert [view._table.isRowHidden(i) for i in range(4)] == [True, False, True, True]
    assert "Показано 1 из 4" in view._filter_count.text()
    view._compression_filter.setCurrentIndex(view._compression_filter.findData("short"))
    assert all(view._table.isRowHidden(i) for i in range(4))
    assert view._table.currentRow() == -1 and view._plot.row == -1
    assert view._candidate_plot is not None and view._candidate_plot.row == -1
    # A graph selection resets only the incompatible filter.
    view._plot.rowSelected.emit(1)
    assert view._coil_filter.currentData() == "short" and view._compression_filter.currentData() == "all"
    assert view._table.currentRow() == view._plot.row == view._candidate_plot.row == 1
    assert not view._table.isRowHidden(1)
    view._compression_filter.setCurrentIndex(view._compression_filter.findData("short"))
    view._candidate_plot.rowSelected.emit(3)
    assert view._coil_filter.currentData() == "all" and view._compression_filter.currentData() == "short"
    assert view._table.currentRow() == 3 and not view._table.isRowHidden(3)
    assert view._candidate_plot_selection is not None and "диагностическая" in view._candidate_plot_selection.text()
    view._coil_filter.setCurrentIndex(view._coil_filter.findData("ok"))
    view._compression_filter.setCurrentIndex(view._compression_filter.findData("ok"))
    view._candidate_min_coil.click()
    assert view._table.currentRow() == 1 and view._coil_filter.currentData() == "all"
    assert view._compression_filter.currentData() == "ok" and not view._table.isRowHidden(1)
    assert path.samples == samples


def test_path_filter_does_not_filter_table_or_graph_csv(qtbot, monkeypatch):
    from dataclasses import replace
    from datetime import datetime, timedelta

    from suspensionlab.i18n import tr
    from suspensionlab.ui import table_export

    class AdvancingClock:
        calls = 0

        @classmethod
        def now(cls, tz):
            cls.calls += 1
            return datetime(2025, 1, 1, tzinfo=tz) + timedelta(seconds=cls.calls)

    monkeypatch.setattr(table_export, "datetime", AdvancingClock)
    from suspensionlab.ui.controller import AppController
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    c = AppController()
    c.new_project("ring")
    candidate = SpringCandidate(350, 230, 150, 77, 120, 12.5)
    model = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=150,
                              spring_characteristic=SpringCharacteristic(350, 12.5, coil_bind_length_mm=150))
    dialog = EquilibriumDialog(c, candidate=candidate)
    qtbot.addWidget(dialog)
    dialog._load.setValue(model.evaluate(12, 1).wheel_support_n)
    dialog._run.click()
    path = dialog._path
    assert path is not None
    view = EquilibriumPathDialog(path, dialog, candidate=candidate)
    qtbot.addWidget(view)
    before = dialog._path_report(path, view._table)
    graph_before = dialog._path_graph_report(path, view._table, view._plot.points, view._plot_metric.currentText())
    view._coil_filter.setCurrentIndex(view._coil_filter.findData("short"))
    assert any(view._table.isRowHidden(i) for i in range(len(path.samples)))
    assert any(not view._table.isRowHidden(i) for i in range(len(path.samples)))
    after = dialog._path_report(path, view._table)
    graph_after = dialog._path_graph_report(path, view._table, view._plot.points, view._plot_metric.currentText())
    def without_export_time(report):
        timestamps = [value for key, value in report.metadata if key == tr("export.timestamp")]
        assert len(timestamps) == 1
        return replace(report, metadata=tuple((key, value) for key, value in report.metadata
                                              if key != tr("export.timestamp"))), timestamps[0]

    before_normalized, before_time = without_export_time(before)
    after_normalized, after_time = without_export_time(after)
    graph_before_normalized, graph_before_time = without_export_time(graph_before)
    graph_after_normalized, graph_after_time = without_export_time(graph_after)
    assert before_time != after_time and graph_before_time != graph_after_time
    assert after_normalized == before_normalized and graph_after_normalized == graph_before_normalized
    assert len(after.rows) == len(graph_after.rows) == len(path.samples)
    assert "все точки" in view._filter_count.text()
    assert tr("equilibrium_path.column.candidate_status") in graph_after.columns
    dialog._load.setValue(dialog._load.value() + 5)
    with pytest.raises(ValueError):
        dialog._path_report(path, view._table)


def test_candidate_filters_empty_and_no_candidate(qtbot):
    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    axle = load_template("ring").front
    path = SpringEquilibrium(axle, 230, coil_bind_length_mm=231).check_path(3, 1000)
    assert not path.samples and path.failure is not None
    view = EquilibriumPathDialog(path, candidate=SpringCandidate(350, 230, 231, 0, 0, 10))
    qtbot.addWidget(view)
    view._coil_filter.setCurrentIndex(view._coil_filter.findData("short"))
    view._compression_filter.setCurrentIndex(view._compression_filter.findData("ok"))
    assert "Показано 0 из 0" in view._filter_count.text()
    assert not view._candidate_min_coil.isEnabled() and view._table.rowCount() == 0
    normal = EquilibriumPathDialog(path)
    qtbot.addWidget(normal)
    normal.show()
    assert normal._coil_filter.isHidden() and normal._compression_filter.isHidden() and normal._filter_count.isHidden()


def test_path_filters_show_overlapping_short_conditions(qtbot):
    from dataclasses import replace

    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    candidate = SpringCandidate(300, 200, 100, 150, 150, 12.5)
    path = SpringEquilibrium(load_template("ring").front, 230).check_path(0, 1000)
    sample = path.samples[0]
    samples = tuple(replace(sample, travel_mm=float(i), spring=replace(sample.spring, length_mm=length))
                    for i, length in enumerate((110., 200., 290.)))
    path = replace(path, samples=samples)
    view = EquilibriumPathDialog(path, candidate=candidate)
    qtbot.addWidget(view)
    view._coil_filter.setCurrentIndex(view._coil_filter.findData("short"))
    view._compression_filter.setCurrentIndex(view._compression_filter.findData("short"))
    assert [view._table.isRowHidden(i) for i in range(3)] == [True, False, True]
    assert "Показано 1 из 3" in view._filter_count.text()
    assert "условие до смыкания не выполнено в 2, по сжатию — в 2" in view._candidate_summary.text()
    assert "Счётчики могут пересекаться" in view._candidate_summary.text()


def test_path_filter_zero_reserves_excludes_physical_boundaries(qtbot):
    from dataclasses import replace

    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    candidate = SpringCandidate(300, 200, 100, 0, 0, 12.5)
    path = SpringEquilibrium(load_template("ring").front, 230).check_path(0, 1000)
    sample = path.samples[0]
    path = replace(path, samples=tuple(replace(sample, travel_mm=float(i),
                        spring=replace(sample.spring, length_mm=length))
                        for i, length in enumerate((100., 200., 300.))))
    view = EquilibriumPathDialog(path, candidate=candidate)
    qtbot.addWidget(view)
    view._coil_filter.setCurrentIndex(view._coil_filter.findData("ok"))
    view._compression_filter.setCurrentIndex(view._compression_filter.findData("ok"))
    assert [view._table.isRowHidden(i) for i in range(3)] == [True, False, True]
