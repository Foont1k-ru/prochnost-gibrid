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
        table = dialog._path_report(path, view._table)
        graph = dialog._path_graph_report(path, view._table, view._plot.points, view._plot_metric.currentText())
        assert len(table.rows) == len(graph.rows) == len(path.samples)
        for i, geometry in enumerate(geoms):
            row = dict(zip(table.columns, table.rows[i], strict=True))
            column = tr("equilibrium_path.column.candidate_coil_condition")
            assert row[column] == tr("candidate_balance_reserve.ok" if geometry.coil_reserve_ok else "candidate_balance_reserve.short")
            assert dict(zip(graph.columns, graph.rows[i], strict=True))[column] == row[column]
        assert "отказ без данных" in dict(table.metadata)[tr("equilibrium_path.candidate_report_limits")]
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
