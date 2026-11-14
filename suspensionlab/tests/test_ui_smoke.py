"""Проверка каркаса нативного окна и основных пользовательских сценариев."""
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from suspensionlab.model.units import UnitKind, UnitSettings
from suspensionlab.ui.controller import Selection
from suspensionlab.ui.main_window import MainWindow
from suspensionlab.ui.widgets.slider_field import SliderField


@pytest.fixture
def window(qtbot, tmp_path: Path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings=settings)
    qtbot.addWidget(win)
    win._confirm_discard_changes = lambda: True
    win.resize(1366, 800)
    win.show()
    yield win
    win.controller.dirty = False


def test_window_and_theme(window, qtbot):
    assert window._tabs.count() == 3
    assert "Подвеска" in window.windowTitle()
    window._apply_theme("light")
    assert window.controller.project.view.theme == "light"
    window._apply_theme("dark")
    assert window.controller.project.view.theme == "dark"
    qtbot.wait(10)


@pytest.mark.parametrize("mode,expected", [("front", "rect"), ("side", "ellipse"), ("top", "rect")])
@pytest.mark.parametrize("template,role", [("ring", "front"), ("live_axle", "rear")])
def test_main_canvas_wheel_shape_and_dimensions(window, mode, expected, template, role):
    from suspensionlab.ui.theme import canvas_colors

    class PainterRecorder:
        def __init__(self):
            self.shapes = []

        def setPen(self, _pen):  # noqa: N802
            pass

        def setBrush(self, _brush):  # noqa: N802
            pass

        def drawRect(self, rect):  # noqa: N802
            self.shapes.append(("rect", rect))

        def drawEllipse(self, rect):  # noqa: N802
            self.shapes.append(("ellipse", rect))

    window.controller.new_project(template)
    canvas = window._canvases[role]
    canvas.set_view_mode(mode)
    recorder = PainterRecorder()
    axle = window.controller.project.axle(role)
    canvas._draw_wheels(recorder, axle, canvas_colors("dark"))
    assert len(recorder.shapes) == 2
    assert all(shape == expected for shape, _rect in recorder.shapes)
    scale = canvas._scale()
    width = axle.wheel.width_mm if mode == "front" else 2 * axle.wheel.r_dynamic_mm
    height = axle.wheel.width_mm if mode == "top" else 2 * axle.wheel.r_dynamic_mm
    for _shape, rect in recorder.shapes:
        assert rect.width() == pytest.approx(width * scale)
        assert rect.height() == pytest.approx(height * scale)


def test_template_save_open_and_undo(window, tmp_path):
    c = window.controller
    c.new_project("ring")
    point = c.project.front.hardpoints["ubj"]
    original = point.z
    c.set_value(point, "z", original + 5)
    c.undo_last()
    assert point.z == original
    c.redo_last()
    assert point.z == original + 5
    path = c.save_project(tmp_path / "project")
    c.new_project("city")
    c.open_project(path)
    assert c.project.front.hardpoints["ubj"].z == original + 5


def test_slider_and_unit_conversion(window, qtbot):
    c = window.controller
    c.new_project("ring")
    c.select(Selection("point", "front", "ubj"))
    fields = window._inspector.findChildren(SliderField)
    field = next(x for x in fields if x._spec.attr == "z")
    field._edit.setText("2500")
    field._on_edit_finished()
    assert c.project.front.hardpoints["ubj"].z == pytest.approx(2500)
    assert field._slider.maximum() * field._step >= 2500
    c.set_units(UnitSettings(length="in"))
    assert c.units.parse("1", UnitKind.LENGTH) == pytest.approx(25.4)
    assert c.units.parse("12 см", UnitKind.LENGTH) == pytest.approx(120)


def test_views_and_template(window, qtbot):
    window.controller.new_project("live_axle")
    window._show_workspace()
    canvas = window._canvases["both"]
    for mode in ("front", "side", "top"):
        canvas.set_view_mode(mode)
        canvas.grab()
    qtbot.wait(10)


def test_autosave_preserves_original_path(window, tmp_path, monkeypatch):
    from suspensionlab.ui import controller as module

    c = window.controller
    saved = c.save_project(tmp_path / "original")
    backup = tmp_path / "autosave.susp.json"
    monkeypatch.setattr(module, "autosave_path", lambda: backup)
    c.set_value(c.project.vehicle, "mass_kg", 1500.0)
    assert c.autosave()
    assert Path(c.project.path) == saved
    assert backup.exists()
    c.save_project()
    assert c.project.path == str(saved)


def test_undo_type_change_preserves_point_and_prior_edits(window):
    c = window.controller
    point = c.project.front.hardpoints["ubj"]
    old = point.z
    point.locked = True
    c.set_value(point, "z", old + 11)
    c.set_axle_type("front", "multilink_front")
    c.undo_last()
    assert c.project.front.hardpoints["ubj"] is point
    assert point.locked
    c.undo_last()
    assert point.z == old
    c.redo_last()
    c.redo_last()
    assert c.project.front.hardpoints["ubj"].z == old + 11


def test_locks_are_scoped_to_axles(window):
    c = window.controller
    c.new_project("ring")
    c.select(Selection("point", "front", "spring_lo"))
    field = next(x for x in window._inspector.findChildren(SliderField) if x._spec.attr == "z")
    field._lock_button.click()
    assert c.is_locked("front.point.spring_lo.z")
    assert not c.is_locked("rear.point.spring_lo.z")
    c.select(Selection("point", "rear", "spring_lo"))
    field = next(x for x in window._inspector.findChildren(SliderField) if x._spec.attr == "z")
    assert not field.is_locked()


def test_snapshot_creation_undo_and_redo(window):
    c = window.controller
    c.add_snapshot("До изменения")
    assert [snapshot.name for snapshot in c.project.snapshots] == ["До изменения"]
    c.undo_last()
    assert not c.project.snapshots
    c.redo_last()
    assert c.project.snapshots[0].name == "До изменения"


def test_configurable_template_dialog(window, qtbot, tmp_path):
    from suspensionlab.ui.dialogs import TemplateDialog

    dialog = TemplateDialog(window)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.selected_key() is None
    assert dialog._front.currentData() == "macpherson_front"
    assert dialog._powertrain.currentData() == "transverse_front"
    dialog._powertrain.setCurrentIndex(dialog._powertrain.findData("longitudinal_transaxle"))
    assert dialog._front_drive.isChecked() and not dialog._rear_drive.isChecked()
    dialog._rear.setCurrentIndex(dialog._rear.findData("torsion_beam_rear"))
    assert not dialog._rear_drive.isEnabled() and not dialog._rear_drive.isChecked()
    project = dialog.selected_project()
    assert project is not None and project.rear.type_code == "torsion_beam_rear"
    assert project.vehicle.powertrain_layout == "longitudinal_transaxle"
    window.controller.new_project(project=project)
    window._show_workspace()
    for mode in ("front", "side", "top"):
        window._canvases["both"].set_view_mode(mode)
        window._canvases["both"].grab()
    path = window.controller.save_project(tmp_path / "configured")
    window.controller.open_project(path)
    assert window.controller.project.front.type_code == "macpherson_front"
    assert window.controller.project.vehicle.powertrain_layout == "longitudinal_transaxle"
    dialog._list.setCurrentRow(1)
    assert dialog._powertrain.currentData() == "longitudinal_transfer"
    assert dialog._front.currentData() == "multilink_front"
    assert dialog._front_drive.isChecked() and dialog._rear_drive.isChecked()
    dialog._rear.setCurrentIndex(dialog._rear.findData("live_axle_coil"))
    assert dialog.selected_project().rear.type_code == "live_axle_coil"
    dialog._list.setCurrentRow(2)
    assert dialog.selected_project() is None and dialog.selected_key() == "ring"


def test_powertrain_inspector_undo_and_views(window, tmp_path):
    from suspensionlab.core.powertrain_layout import layout_diagram

    c = window.controller
    c.new_project("ring")
    c.select(Selection("vehicle"))
    row = next(row for row in window._inspector._rows if row.spec.attr == "powertrain_layout")
    combo = row.widget
    assert combo.currentData() == "unspecified"
    combo.setCurrentIndex(combo.findData("longitudinal_transfer"))
    assert c.project.vehicle.powertrain_layout == "longitudinal_transfer"
    assert layout_diagram(c.project).status == "ok"
    c.undo_last()
    assert c.project.vehicle.powertrain_layout == "unspecified" and combo.currentData() == "unspecified"
    c.redo_last()
    assert c.project.vehicle.powertrain_layout == "longitudinal_transfer"
    window._show_workspace()
    for role in ("front", "rear", "both"):
        for mode in ("front", "side", "top"):
            canvas = window._canvases[role]
            canvas.set_view_mode(mode)
            canvas.grab()
    path = c.save_project(tmp_path / "powertrain")
    c.open_project(path)
    assert c.project.vehicle.powertrain_layout == "longitudinal_transfer"


def test_powertrain_diagnostic_updates_and_selects_vehicle(window, qtbot):
    from suspensionlab.model.templates import VehicleTemplateOptions, create_vehicle_template

    project = create_vehicle_template(VehicleTemplateOptions("passenger", "double_wishbone", "multilink_rear",
                                                             False, True, "transverse_front"))
    controller = window.controller
    controller.new_project(project=project)
    panel = window._diagnostics
    item = next(panel._list.item(i) for i in range(panel._list.count())
                if (issue := panel._list.item(i).data(0x0100)) is not None
                and issue.key == "diag.powertrain_incompatible")
    assert "включена только задняя" in item.text()
    panel._on_item(item)
    assert controller.selection == Selection("vehicle")
    controller.set_value(controller.project.front.drivetrain, "driven", True)
    assert not any(issue.key == "diag.powertrain_incompatible" for issue in controller.issues)
    controller.undo_last()
    assert any(issue.key == "diag.powertrain_incompatible" for issue in controller.issues)
    controller.redo_last()
    assert not any(issue.key == "diag.powertrain_incompatible" for issue in controller.issues)


def test_template_warns_about_incompatible_powertrain_before_creation(window, qtbot):
    from suspensionlab.ui.dialogs import TemplateDialog

    dialog = TemplateDialog(window)
    qtbot.addWidget(dialog)
    dialog._front_drive.setChecked(False)
    dialog._rear_drive.setChecked(True)
    assert "Несовместимо" in dialog._powertrain_hint.text()
    selected = dialog.selected_project()
    assert selected is not None and not selected.front.drivetrain.driven and selected.rear.drivetrain.driven
    dialog._powertrain.setCurrentIndex(dialog._powertrain.findData("longitudinal_transfer"))
    assert "Условная компоновка" in dialog._powertrain_hint.text()
    dialog._powertrain.setCurrentIndex(dialog._powertrain.findData("unspecified"))
    assert "не задана" in dialog._powertrain_hint.text()


def test_analysis_dialog_results_and_invalidation(window, qtbot):
    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.stroke import StrokeLimits
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    window.controller.new_project("ring")
    before = window.controller.project.to_dict()
    dialog = AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(-1)
    dialog._to.setValue(1)
    dialog._spring.setChecked(True)
    dialog._spring_length.setValue(230)
    dialog._coil_bind.setValue(150)
    dialog._damper.setChecked(True)
    dialog._damper_min.setValue(350)
    dialog._damper_max.setValue(450)
    dialog._run.click()
    assert dialog._table.rowCount() == 3
    assert "нерешённых: 0" in dialog._status.text()
    result = analyze_corner(window.controller.project.front, window.controller.project.vehicle, [-1, 0, 1],
                            spring_mount="lower_arm", static_spring_length_mm=230, coil_bind_length_mm=150,
                            damper_mount="lower_arm", damper_limits=StrokeLimits(350, 450))
    sample = result.samples[1]
    assert sample is not None and sample.spring is not None and sample.spring.state is not None and sample.damper is not None
    assert float(dialog._table.item(1, 1).text()) == pytest.approx(sample.geometry.camber_deg, abs=0.0005)
    assert float(dialog._table.item(1, 3).text()) == pytest.approx(sample.spring.state.length_mm, abs=0.005)
    assert float(dialog._table.item(1, 5).text()) == pytest.approx(sample.spring.state.force_n, abs=0.05)
    assert float(dialog._table.item(1, 6).text()) == pytest.approx(sample.damper.length_mm, abs=0.005)
    assert "Между заданными упорами" in dialog._table.item(1, 8).text()
    assert window.controller.project.to_dict() == before
    dialog._side.setCurrentIndex(1)
    assert dialog._table.rowCount() == 0
    dialog._run.click()
    assert dialog._table.rowCount() == 3
    point = window.controller.project.front.hardpoints["ubj"]
    window.controller.set_value(point, "z", point.z + 1)
    assert dialog._table.rowCount() == 0
    dialog._role.setCurrentIndex(1)
    assert not dialog._run.isEnabled()
    assert "пока не реализован" in dialog._status.text()


def test_analysis_plot_uses_samples_and_tracks_table_selection(window, qtbot):
    from PySide6.QtCore import QPoint, Qt

    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    window.controller.new_project("ring")
    dialog = AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(-1)
    dialog._to.setValue(1)
    dialog._run.click()
    dialog._view_tabs.setCurrentIndex(1)
    qtbot.wait(50)
    result = analyze_corner(window.controller.project.front, window.controller.project.vehicle, [-1, 0, 1])
    assert result.samples[0] is not None
    assert dialog._plot.points[0].values[0] == result.samples[0].geometry.camber_deg
    assert dialog._plot.row == 1
    dialog._table.setCurrentCell(2, 0)
    assert dialog._plot.row == 2
    geometry = dialog._plot._geometry()
    assert geometry is not None
    target = dialog._plot._screen(-1, result.samples[0].geometry.camber_deg, geometry)
    qtbot.mouseClick(dialog._plot, Qt.MouseButton.LeftButton, pos=QPoint(round(target.x()), round(target.y())))
    assert dialog._table.currentRow() == 0 and dialog._plot.row == 0
    assert not dialog._plot.grab().isNull()
    dialog._plot_metric.setCurrentIndex(2)  # Нет заданной пружины — нет данных.
    assert dialog._plot._geometry() is None
    assert not dialog._plot.grab().isNull()
    dialog._side.setCurrentIndex(1)
    assert dialog._plot.points == () and dialog._plot.row == -1
    dialog._run.click()
    assert len(dialog._plot.points) == 3
    dialog._from.setValue(0)
    dialog._to.setValue(0)
    dialog._run.click()
    dialog._plot_metric.setCurrentIndex(0)
    assert dialog._plot._geometry() is not None  # Одна точка и нулевой размах не ломают масштаб.
    assert not dialog._plot.grab().isNull()


def test_sweep_plot_with_gap_conflict_and_unreachable_row(window, qtbot):
    from PySide6.QtCore import QPoint, Qt

    from suspensionlab.core.sweep_plot import PLOT_METRICS, PlotPoint
    from suspensionlab.ui.canvas.sweep_plot import SweepPlot

    plot = SweepPlot(window)
    qtbot.addWidget(plot)
    plot.resize(500, 300)
    plot.show()
    def point(x, value, conflict=False):
        return PlotPoint(x, (value,) + (None,) * (len(PLOT_METRICS) - 1), conflict)
    plot.set_points((point(-1, 1), point(0, None), point(1, 2, True)))
    assert not plot.grab().isNull()
    selected, descriptions = [], []
    plot.rowSelected.connect(selected.append)
    plot.selectionTextChanged.connect(descriptions.append)
    plot.set_row(0)
    assert "значение 1" in descriptions[-1]
    plot.set_row(1)
    assert "нет данных" in descriptions[-1]
    plot.set_row(2)
    assert "обнаружен конфликт" in descriptions[-1]
    geometry = plot._geometry()
    assert geometry is not None
    target = plot._screen(0, 1.5, geometry)
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=QPoint(round(target.x()), round(target.y())))
    assert selected == [1]  # Даже нерассчитанную строку можно выбрать и прочитать её ошибку.
    plot.set_row(2)
    assert not plot.grab().isNull()


@pytest.mark.parametrize("kind", ["analysis", "antiroll"])
def test_graph_csv_exports_all_raw_values_states_and_invalidates(window, qtbot, tmp_path, monkeypatch, kind):
    import csv

    from suspensionlab.ui import table_export
    from suspensionlab.ui.analysis_dialog import AnalysisDialog
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    before = window.controller.project.to_dict()
    dialog = AnalysisDialog(window.controller, window) if kind == "analysis" else AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(-1)
    dialog._to.setValue(1)
    if kind == "analysis":
        dialog._spring.setChecked(True)
        dialog._spring_length.setValue(230)
        dialog._coil_bind.setValue(231)
    else:
        dialog._axis_x.setText("-250")
        dialog._axis_z.setText("320")
        dialog._rate.setText("1000")
        dialog._show_spring.setChecked(True)
        dialog._spring_length.setValue(230)
        dialog._coil_bind.setValue(231)
    assert not dialog._plot_export_button.isEnabled()
    dialog._run.click()
    assert dialog._plot_export_button.isEnabled() and dialog._plot.points[1].conflict
    dialog._plot_metric.setCurrentIndex(0)
    target = tmp_path / kind
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    dialog._plot_export_button.click()
    with target.with_suffix(".csv").open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.reader(handle, delimiter=";"))
    index = records.index([])
    columns, rows = records[index + 1], records[index + 2:]
    assert len(rows) == 3 and len(columns) == len(rows[1])
    assert float(rows[1][1]) == dialog._plot.points[1].values[0]
    conflict_col = columns.index("Обнаруженный конфликт элемента")
    assert rows[1][conflict_col] == "да"
    if kind == "analysis":
        clearance = columns.index("Запас до смыкания пружины, мм")
        assert float(rows[1][clearance]) == pytest.approx(-1)
    else:
        clearance = columns.index("Запас до смыкания пружины П, мм")
        assert float(rows[1][clearance]) == pytest.approx(-1)
        assert float(rows[0][columns.index("Ход П, мм")]) == 1
    assert any("не подтверждает безопасность" in field for record in records[:index] for field in record)
    assert window.controller.project.to_dict() == before
    dialog._from.setValue(0)
    assert not dialog._plot_export_button.isEnabled() and not dialog._plot.points


@pytest.mark.parametrize("kind", ["analysis", "antiroll"])
def test_graph_csv_cancel_and_inconsistent_data_do_not_write(window, qtbot, tmp_path, monkeypatch, kind):
    from suspensionlab.ui import table_export
    from suspensionlab.ui.analysis_dialog import AnalysisDialog
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    dialog = AnalysisDialog(window.controller, window) if kind == "analysis" else AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(0)
    if kind == "antiroll":
        dialog._axis_x.setText("-250")
        dialog._axis_z.setText("320")
        dialog._rate.setText("1000")
    dialog._run.click()
    target = tmp_path / "existing.csv"
    target.write_text("старые данные", encoding="utf-8")
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    dialog._export_plot()
    assert target.read_text(encoding="utf-8") == "старые данные"
    alerts = []
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    monkeypatch.setattr(table_export.QMessageBox, "warning", lambda *args: alerts.append(args))
    dialog._table.takeItem(0, 8 if kind == "analysis" else 12)
    dialog._export_plot()
    assert alerts and target.read_text(encoding="utf-8") == "старые данные"


def test_analysis_dialog_rejects_incomplete_inputs_and_clears_old_results(window, qtbot):
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    window.controller.new_project("ring")
    dialog = AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(0)
    dialog._run.click()
    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 3).text() == "—"
    dialog._spring.setChecked(True)
    assert dialog._table.rowCount() == 0
    dialog._run.click()
    assert "длину пружины" in dialog._status.text()
    dialog._spring_length.setValue(230)
    dialog._damper.setChecked(True)
    dialog._damper_min.setValue(350)
    dialog._run.click()
    assert "оба предела" in dialog._status.text()
    assert dialog._table.rowCount() == 0
    dialog._damper_min.setValue(0)
    dialog._run.click()
    assert "не заданы" in dialog._table.item(0, 8).text()
    dialog._from.setValue(20)
    dialog._run.click()
    assert dialog._table.rowCount() == 0
    assert "не выполнен" in dialog._status.text()
    window.controller.set_axle_type("front", "macpherson_front")
    assert not dialog._run.isEnabled()
    window.controller.new_project("ring")
    assert dialog._run.isEnabled()
    assert dialog._table.rowCount() == 0


def test_analysis_dialog_clears_results_if_wheel_projection_fails(window, qtbot, monkeypatch):
    from suspensionlab.core import metrics
    from suspensionlab.core.double_wishbone import KinematicsError
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    window.controller.new_project("ring")
    dialog = AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(0)
    dialog._run.click()
    assert dialog._table.rowCount() == 1 and dialog._export_button.isEnabled()

    def reject_projection(_normal, _forward, travel):
        raise KinematicsError(travel, "проекция оси колеса вырождена")

    monkeypatch.setattr(metrics, "_validate_wheel_projections", reject_projection)
    dialog._run.click()
    assert "проекция оси колеса вырождена" in dialog._status.text()
    assert dialog._table.rowCount() == 0 and not dialog._export_button.isEnabled()
    assert not dialog._frames and dialog._preview.frame is None


def test_calculation_input_failures_are_logged(window, qtbot, caplog):
    from suspensionlab.ui.analysis_dialog import AnalysisDialog
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    window.controller.new_project("ring")
    analysis = AnalysisDialog(window.controller, window)
    qtbot.addWidget(analysis)
    analysis._spring.setChecked(True)
    analysis._run.click()
    assert "Расчёт хода не выполнен" in caplog.text
    assert "длину пружины" in analysis._status.text()
    equilibrium = EquilibriumDialog(window.controller, window)
    qtbot.addWidget(equilibrium)
    equilibrium._run.click()
    assert "Поиск баланса не выполнен" in caplog.text
    assert not equilibrium._export_button.isEnabled()


def test_analysis_action_opens_dialog(window, monkeypatch):
    from suspensionlab.ui import main_window

    seen = []

    class FakeDialog:
        def __init__(self, controller, parent):
            seen.append((controller, parent))

        def exec(self):
            seen.append("opened")

        def deleteLater(self):  # noqa: N802
            seen.append("released")

    monkeypatch.setattr(main_window, "AnalysisDialog", FakeDialog)
    window.action_analysis.trigger()
    assert seen == [(window.controller, window), "opened", "released"]


def test_analysis_dialog_shows_partial_failure_and_mechanical_conflicts(window, qtbot, monkeypatch, caplog):
    from dataclasses import replace

    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.double_wishbone import KinematicsError
    from suspensionlab.core.sweep import SweepPoint
    from suspensionlab.ui import analysis_dialog

    window.controller.new_project("ring")
    dialog = analysis_dialog.AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(1)
    original = analyze_corner(window.controller.project.front, window.controller.project.vehicle, [0, 1])
    first = original.samples[0]
    assert first is not None
    failure = KinematicsError(1, "test failure")
    partial = replace(original, sweep=replace(original.sweep, points=(original.sweep.points[0], SweepPoint(1, None, failure))),
                      samples=(first, None))
    monkeypatch.setattr(analysis_dialog, "analyze_corner", lambda *args, **kwargs: partial)
    dialog._run.click()
    assert dialog._table.rowCount() == 2
    assert dialog._table.item(1, 1).text() == "—"
    assert "test failure" in dialog._table.item(1, 8).text()
    assert "нерешённых: 1" in dialog._status.text()
    assert "Расчёт хода: нерешённых строк 1" in caplog.text and "test failure" in caplog.text
    monkeypatch.setattr(analysis_dialog, "analyze_corner", analyze_corner)
    dialog._to.setValue(0)
    dialog._spring.setChecked(True)
    dialog._spring_length.setValue(230)
    dialog._coil_bind.setValue(230)
    dialog._damper.setChecked(True)
    dialog._damper_min.setValue(100)
    dialog._damper_max.setValue(200)
    dialog._run.click()
    assert dialog._table.item(0, 5).text() == "—"
    assert "Смыкание" in dialog._table.item(0, 8).text()
    assert "Превышен упор отбоя" in dialog._table.item(0, 8).text()


def test_analysis_dialog_explicit_damper_force_and_stop(window, qtbot):
    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.damper import LinearDamperCharacteristic, evaluate_linear_damping
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    window.controller.new_project("ring")
    before = window.controller.project.to_dict()
    dialog = AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(0)
    assert not dialog._damping.isEnabled()
    dialog._damper.setChecked(True)
    dialog._damping.setChecked(True)
    dialog._run.click()
    assert dialog._table.rowCount() == 0 and "введите скорость" in dialog._status.text()
    dialog._velocity.setText("-20,0")
    dialog._compression.setText("2")
    dialog._rebound.setText("4")
    dialog._run.click()
    assert dialog._table.rowCount() == 1
    sample = analyze_corner(window.controller.project.front, window.controller.project.vehicle, [0],
                            damper_mount="lower_arm").samples[0]
    assert sample is not None and sample.damper is not None
    expected = evaluate_linear_damping(sample.damper, LinearDamperCharacteristic(2, 4), -20)
    assert float(dialog._table.item(0, 9).text()) == pytest.approx(expected.compression_velocity_mm_s, abs=0.005)
    assert float(dialog._table.item(0, 10).text()) == pytest.approx(expected.wheel_force_n, abs=0.05)
    assert float(dialog._table.item(0, 11).text()) == pytest.approx(expected.dissipated_power_w, abs=0.005)
    assert "не заданы" in dialog._table.item(0, 8).text()
    dialog._velocity.setText("20")
    assert dialog._table.rowCount() == 0
    dialog._run.click()
    assert float(dialog._table.item(0, 10).text()) < 0
    dialog._damper_min.setValue(100)
    dialog._damper_max.setValue(200)
    dialog._run.click()
    assert dialog._table.item(0, 10).text() == "—"
    assert "не определена" in dialog._table.item(0, 8).text()
    assert window.controller.project.to_dict() == before
    dialog._damper.setChecked(False)
    assert not dialog._damping.isChecked() and not dialog._velocity.isEnabled()


def test_analysis_damping_missing_invalid_and_fine_grid(window, qtbot):
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    window.controller.new_project("ring")
    dialog = AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(0.2)
    dialog._step.setValue(0.1)
    dialog._damper.setChecked(True)
    dialog._damping.setChecked(True)
    dialog._compression.setText("0")
    dialog._rebound.setText("1")
    for invalid in ("", "nan", "inf", "10001", "1,2,3"):
        dialog._velocity.setText(invalid)
        dialog._run.click()
        assert dialog._table.rowCount() == 0
        assert "введите скорость" in dialog._status.text()
    dialog._velocity.setText("0")
    dialog._run.click()
    assert dialog._table.rowCount() == 3
    assert float(dialog._table.item(0, 10).text()) == 0
    dialog._from.setValue(-100)
    dialog._to.setValue(100)
    dialog._run.click()
    assert dialog._table.rowCount() == 0
    assert "401" in dialog._status.text()


def test_antiroll_dialog_compares_with_core_and_invalidates(window, qtbot):
    from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    before = window.controller.project.to_dict()
    dialog = AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(-1)
    dialog._to.setValue(1)
    dialog._run.click()
    assert dialog._table.rowCount() == 0 and "Введите X и Z" in dialog._status.text()
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    dialog._run.click()
    assert dialog._table.rowCount() == 3
    result = AntiRollStudy(window.controller.project.front, AntiRollScenario(-250, 320, 1000)).sweep([(-1, 1), (0, 0), (1, -1)])
    state = result.points[2].state
    assert state is not None
    assert float(dialog._table.item(2, 8).text()) == pytest.approx(state.twist_deg, abs=0.005)
    assert float(dialog._table.item(2, 9).text()) == pytest.approx(state.torque_nm, abs=0.005)
    assert float(dialog._table.item(2, 10).text()) == pytest.approx(state.left.compression_force_n, abs=0.05)
    assert float(dialog._table.item(2, 11).text()) == pytest.approx(state.right.compression_force_n, abs=0.05)
    assert window.controller.project.to_dict() == before
    dialog._mode.setCurrentIndex(0)
    assert dialog._table.rowCount() == 0
    dialog._run.click()
    assert float(dialog._table.item(2, 9).text()) == pytest.approx(0, abs=0.01)
    point = window.controller.project.front.hardpoints["arb_lo"]
    window.controller.set_value(point, "z", point.z + 1)
    assert dialog._table.rowCount() == 0
    dialog._role.setCurrentIndex(1)
    assert not dialog._run.isEnabled() and "пока не реализован" in dialog._status.text()


@pytest.mark.parametrize("kind", ["analysis", "antiroll"])
def test_chart_tab_pauses_playback(window, qtbot, kind):
    from suspensionlab.ui.analysis_dialog import AnalysisDialog
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    dialog = AnalysisDialog(window.controller, window) if kind == "analysis" else AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(2)
    if kind == "antiroll":
        dialog._axis_x.setText("-250")
        dialog._axis_z.setText("320")
        dialog._rate.setText("1000")
    dialog._run.click()
    dialog._playback.toggle()
    assert dialog._playback._timer.isActive()
    dialog._view_tabs.setCurrentIndex(1)
    assert not dialog._playback._timer.isActive()
    assert "пауза" in dialog._playback._message.text().lower()


def test_antiroll_plot_selection_and_conflicts(window, qtbot):
    from PySide6.QtCore import QPoint, Qt

    from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    dialog = AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(-1)
    dialog._to.setValue(1)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    dialog._run.click()
    dialog._view_tabs.setCurrentIndex(1)
    dialog._plot_metric.setCurrentIndex(2)  # Скручивание
    qtbot.wait(50)
    state = AntiRollStudy(window.controller.project.front, AntiRollScenario(-250, 320, 1000)).sweep([(-1, 1)]).points[0].state
    assert state is not None
    assert dialog._plot.points[0].values[2] == pytest.approx(state.twist_deg, abs=1e-8)
    geometry = dialog._plot._geometry()
    assert geometry is not None
    target = dialog._plot._screen(-1, dialog._plot.points[0].values[2], geometry)
    qtbot.mouseClick(dialog._plot, Qt.MouseButton.LeftButton, pos=QPoint(round(target.x()), round(target.y())))
    assert dialog._table.currentRow() == 0 and dialog._plot.row == 0
    assert not dialog._plot.grab().isNull()
    dialog._show_spring.setChecked(True)
    dialog._spring_length.setValue(230)
    dialog._coil_bind.setValue(231)
    assert dialog._plot.points == ()
    dialog._run.click()
    assert dialog._plot.points[1].conflict
    assert not dialog._plot.grab().isNull()
    dialog._mode.setCurrentIndex(0)
    assert dialog._plot.points == ()


def test_antiroll_dialog_input_validation_and_failure(window, qtbot, monkeypatch, caplog):
    from suspensionlab.core.antiroll import AntiRollPoint, AntiRollSweep
    from suspensionlab.ui import antiroll_dialog

    window.controller.new_project("ring")
    dialog = antiroll_dialog.AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(0)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    for invalid in ("", "nan", "-1", "10000001"):
        dialog._rate.setText(invalid)
        dialog._run.click()
        assert dialog._table.rowCount() == 0
        assert "Введите X и Z" in dialog._status.text()
    dialog._rate.setText("0")
    dialog._run.click()
    assert float(dialog._table.item(0, 9).text()) == 0
    dialog._from.setValue(-100)
    dialog._to.setValue(100)
    dialog._step.setValue(0.1)
    dialog._run.click()
    assert dialog._table.rowCount() == 0 and "401" in dialog._status.text()
    dialog._from.setValue(0)
    dialog._to.setValue(0)

    class FailingStudy:
        def __init__(self, *args):
            pass

        def sweep(self, *args, **kwargs):
            return AntiRollSweep((AntiRollPoint(0, 0, None, "test failure"),), ())

    monkeypatch.setattr(antiroll_dialog, "AntiRollStudy", FailingStudy)
    dialog._run.click()
    assert dialog._table.item(0, 9).text() == "—"
    assert dialog._table.item(0, 12).text() == "test failure"
    assert "нерешённых: 1" in dialog._status.text()
    assert "Расчёт стабилизатора не выполнен" in caplog.text
    assert "Расчёт стабилизатора: нерешённых строк 1" in caplog.text
    assert "test failure" in caplog.text


def test_antiroll_action_opens_dialog(window, monkeypatch):
    from suspensionlab.ui import main_window

    seen = []

    class FakeDialog:
        def __init__(self, controller, parent):
            seen.append((controller, parent))

        def exec(self):
            seen.append("opened")

        def deleteLater(self):  # noqa: N802
            seen.append("released")

    monkeypatch.setattr(main_window, "AntiRollDialog", FakeDialog)
    window.action_antiroll.trigger()
    assert seen == [(window.controller, window), "opened", "released"]


def test_pose_preview_selection_steps_conflict_and_invalidation(window, qtbot):
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    window.controller.new_project("ring")
    dialog = AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(-1)
    dialog._to.setValue(1)
    dialog._step.setValue(0.5)
    dialog._spring.setChecked(True)
    dialog._spring_length.setValue(230)
    dialog._coil_bind.setValue(230)
    dialog._damper.setChecked(True)
    dialog._damper_min.setValue(100)
    dialog._damper_max.setValue(200)
    dialog._run.click()
    assert dialog._table.rowCount() == 5
    assert dialog._preview.frame is not None
    assert dialog._preview.frame.travel_mm == 0
    assert "геометрическ" in dialog._preview_status.text().lower()
    assert "Смыкание" in dialog._preview_status.text()
    assert "Превышен упор отбоя" in dialog._preview_status.text()
    z0 = dialog._preview.frame.center[2]
    bounds = dialog._preview.bounds
    dialog._next.click()
    assert dialog._preview.frame.travel_mm == pytest.approx(0.5)
    assert dialog._preview.frame.center[2] == pytest.approx(z0 + 0.5, abs=1e-6)
    assert dialog._preview.bounds == bounds
    dialog._previous.click()
    assert dialog._preview.frame.travel_mm == 0
    dialog._table.setCurrentCell(0, 0)
    assert dialog._slider.value() == 0 and dialog._preview.frame.travel_mm == -1
    dialog._preview.grab()
    dialog._side.setCurrentIndex(1)
    assert dialog._preview.frame is None and not dialog._slider.isEnabled()
    dialog._run.click()
    assert dialog._preview.frame is not None and dialog._preview.frame.center[1] < 0
    window.controller.new_project("city")
    assert dialog._preview.frame is None and dialog._table.rowCount() == 0


def test_pose_preview_handles_unsolved_row_without_stale_image(window, qtbot, monkeypatch):
    from dataclasses import replace

    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.double_wishbone import KinematicsError
    from suspensionlab.core.sweep import SweepPoint
    from suspensionlab.ui import analysis_dialog

    window.controller.new_project("ring")
    dialog = analysis_dialog.AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(1)
    original = analyze_corner(window.controller.project.front, window.controller.project.vehicle, [0, 1])
    failure = KinematicsError(1, "test")
    partial = replace(original, sweep=replace(original.sweep, points=(original.sweep.points[0], SweepPoint(1, None, failure))),
                      samples=(original.samples[0], None))
    monkeypatch.setattr(analysis_dialog, "analyze_corner", lambda *args, **kwargs: partial)
    dialog._run.click()
    assert dialog._preview.frame is not None
    dialog._next.click()
    assert dialog._preview.frame is None and "недоступна" in dialog._preview_status.text()
    dialog._previous.click()
    assert dialog._preview.frame is not None


def test_antiroll_preview_steps_both_views_and_invalidates(window, qtbot):
    from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    dialog = AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(-1)
    dialog._to.setValue(1)
    dialog._step.setValue(0.5)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    dialog._run.click()
    assert dialog._table.rowCount() == 5
    assert dialog._preview.frame is not None and dialog._preview.frame.left_travel_mm == 0
    assert dialog._preview.axis_x == -250 and dialog._preview.axis_z == 320
    assert "препятствия и прочность не проверены" in dialog._preview_status.text().lower()
    bounds = dict(dialog._preview.bounds)
    dialog._next.click()
    state = dialog._preview.frame
    assert state is not None and state.left_travel_mm == pytest.approx(0.5)
    assert state.right_travel_mm == pytest.approx(-0.5)
    reference = AntiRollStudy(window.controller.project.front, AntiRollScenario(-250, 320, 1000)).sweep([(0.5, -0.5)])
    assert reference.points[0].state is not None
    assert state.left.lower_mm == pytest.approx(reference.points[0].state.left.lower_mm, abs=1e-7)
    assert state.right.upper_mm == pytest.approx(reference.points[0].state.right.upper_mm, abs=1e-7)
    assert dialog._preview.bounds == bounds
    dialog._preview.grab()
    dialog._view.setCurrentIndex(1)
    assert dialog._preview.mode == "top" and dialog._preview.frame is state
    dialog._preview.grab()
    dialog._previous.click()
    assert dialog._preview.frame.left_travel_mm == 0
    dialog._table.setCurrentCell(0, 0)
    assert dialog._slider.value() == 0 and dialog._preview.frame.left_travel_mm == -1
    dialog._rate.setText("2000")
    assert dialog._preview.frame is None and dialog._table.rowCount() == 0 and not dialog._slider.isEnabled()
    dialog._run.click()
    assert dialog._preview.frame is not None
    window.controller.new_project("city")
    assert dialog._preview.frame is None and dialog._table.rowCount() == 0


def test_antiroll_preview_does_not_reuse_stale_state_on_failure(window, qtbot, monkeypatch):
    from suspensionlab.core.antiroll import AntiRollPoint, AntiRollScenario, AntiRollStudy, AntiRollSweep
    from suspensionlab.ui import antiroll_dialog

    window.controller.new_project("ring")
    dialog = antiroll_dialog.AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(1)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    good = AntiRollStudy(window.controller.project.front, AntiRollScenario(-250, 320, 1000)).sweep([(0, 0)]).points[0]

    class PartialStudy:
        def __init__(self, *args):
            pass

        def sweep(self, *args, **kwargs):
            return AntiRollSweep((good, AntiRollPoint(1, -1, None, "test failure")), ())

    monkeypatch.setattr(antiroll_dialog, "AntiRollStudy", PartialStudy)
    dialog._run.click()
    assert dialog._preview.frame is not None
    bounds = dict(dialog._preview.bounds)
    dialog._next.click()
    assert dialog._preview.frame is None and "недоступна" in dialog._preview_status.text()
    assert "test failure" in dialog._table.item(1, 12).text()
    dialog._previous.click()
    assert dialog._preview.frame is not None and dialog._preview.bounds == bounds


def test_combined_preview_uses_exact_antiroll_poses_on_both_sides(window, qtbot):
    from math import dist

    from suspensionlab.core.damper import LowerArmDamper
    from suspensionlab.core.double_wishbone import DoubleWishbone
    from suspensionlab.core.springs import lower_arm_point
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    axle = window.controller.project.front
    original = window.controller.project.to_dict()
    dialog = AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(0)
    dialog._to.setValue(1)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    dialog._show_spring.setChecked(True)
    dialog._show_damper.setChecked(True)
    dialog._run.click()
    dialog._next.click()
    row = dialog._points[1]
    assert row.state is not None and row.left_pose is not None and row.right_pose is not None
    left, right = dialog._preview.left_suspension, dialog._preview.right_suspension
    assert left is not None and right is not None
    assert left.travel_mm == 1 and right.travel_mm == -1
    assert left.spring is not None and left.damper is not None
    assert right.spring is not None and right.damper is not None
    for name, pose, view, link in (("left", row.left_pose, left, row.state.left),
                                   ("right", row.right_pose, right, row.state.right)):
        model = DoubleWishbone(axle, name)
        damper = LowerArmDamper(model, axle)
        assert dist(*view.damper) == pytest.approx(damper.evaluate(pose).length_mm)
        arb = axle.hardpoints["arb_lo"]
        import numpy as np
        lower = np.array((arb.x, model.sign * arb.y, arb.z))
        assert link.lower_mm == pytest.approx(lower_arm_point(model, pose, lower))
        assert view.lower_ball == pytest.approx(pose.point(model.points["lbj"], model.center0))
    assert window.controller.project.to_dict() == original
    dialog._preview.grab()
    dialog._view.setCurrentIndex(1)
    dialog._preview.grab()
    dialog._show_spring.setChecked(False)
    assert dialog._preview.frame is None and dialog._table.rowCount() == 0
    dialog._run.click()
    assert dialog._preview.left_suspension.spring is None
    assert dialog._preview.left_suspension.damper is not None


def test_combined_preview_marks_missing_overlay_instead_of_inventing_it(window, qtbot):
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    axle = window.controller.project.front
    axle.hardpoints["spring_lo"].x = float("nan")
    dialog = AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(0)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    dialog._show_spring.setChecked(True)
    dialog._run.click()
    assert dialog._preview.frame is not None
    assert dialog._preview.left_suspension is None and dialog._preview.right_suspension is None
    assert "только стабилизатор" in dialog._preview_status.text()


def test_combined_checks_unknown_known_conflict_and_invalidation(window, qtbot):
    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.stroke import StrokeLimits
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    dialog = AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(0)
    dialog._to.setValue(1)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    assert not dialog._spring_length.isEnabled() and not dialog._damper_min.isEnabled()
    dialog._show_spring.setChecked(True)
    dialog._show_damper.setChecked(True)
    dialog._run.click()
    assert "длина в статике неизвестна" in dialog._table.item(0, 14).text()
    assert "не заданы" in dialog._table.item(0, 16).text()
    assert dialog._table.item(0, 13).text() == "— / —"
    dialog._spring_length.setValue(230)
    dialog._coil_bind.setValue(150)
    dialog._damper_min.setValue(350)
    dialog._damper_max.setValue(450)
    assert dialog._table.rowCount() == 0 and dialog._preview.frame is None
    dialog._run.click()
    dialog._next.click()
    for side, travel, index in (("left", 1, 0), ("right", -1, 1)):
        result = analyze_corner(window.controller.project.front, window.controller.project.vehicle, [travel], side=side,
                                spring_mount="lower_arm", static_spring_length_mm=230, coil_bind_length_mm=150,
                                damper_mount="lower_arm", damper_limits=StrokeLimits(350, 450)).samples[0]
        assert result is not None and result.spring is not None and result.spring.state is not None and result.damper is not None
        assert float(dialog._table.item(1, 13).text().split(" / ")[index]) == pytest.approx(result.spring.state.length_mm, abs=0.0051)
        assert float(dialog._table.item(1, 15).text().split(" / ")[index]) == pytest.approx(result.damper.length_mm, abs=0.0051)
    assert "выше заданной длины смыкания" in dialog._preview_status.text()
    assert "Между заданными упорами" in dialog._preview_status.text()
    dialog._coil_bind.setValue(231)
    dialog._damper_min.setValue(100)
    dialog._damper_max.setValue(200)
    dialog._run.click()
    assert "СМЫКАНИЕ ВИТКОВ" in dialog._preview_status.text()
    assert "Превышен упор отбоя" in dialog._preview_status.text()
    assert dialog._preview.frame is not None  # диагностическая геометрия, не физическое разрешение


def test_combined_checks_reject_incomplete_limits(window, qtbot):
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    dialog = AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(0)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    dialog._show_spring.setChecked(True)
    dialog._coil_bind.setValue(150)
    dialog._run.click()
    assert dialog._table.rowCount() == 0 and "длина пружины в статике" in dialog._status.text()
    dialog._spring_length.setValue(230)
    dialog._show_damper.setChecked(True)
    dialog._damper_min.setValue(350)
    dialog._run.click()
    assert dialog._table.rowCount() == 0 and "оба предела" in dialog._status.text()
    dialog._damper_max.setValue(450)
    dialog._coil_bind.setValue(250)
    dialog._run.click()
    assert dialog._table.rowCount() == 0 and "меньше" in dialog._status.text()
    dialog._show_spring.setChecked(False)
    dialog._run.click()
    assert dialog._table.rowCount() == 1
    assert "не включено" in dialog._table.item(0, 14).text()


def test_playback_in_corner_dialog_stops_before_coil_bind_and_on_edits(window, qtbot):
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    window.controller.new_project("ring")
    dialog = AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(0)
    dialog._to.setValue(2)
    dialog._spring.setChecked(True)
    dialog._spring_length.setValue(230)
    dialog._coil_bind.setValue(229.9)
    dialog._run.click()
    assert dialog._table.rowCount() == 3 and dialog._table.currentRow() == 0
    assert dialog._playback_problem(0) is None
    assert dialog._playback_problem(1) is not None
    dialog._playback._button.click()
    assert dialog._playback._timer.isActive()
    dialog._playback.advance()
    assert not dialog._playback._timer.isActive()
    assert dialog._table.currentRow() == 0
    assert "конфликт пружины" in dialog._playback._message.text()
    dialog._next.click()  # ручной диагностический показ по-прежнему возможен
    assert dialog._table.currentRow() == 1 and dialog._preview.frame is not None
    dialog._playback._button.click()
    assert not dialog._playback._timer.isActive()
    dialog._coil_bind.setValue(0)  # неизведанный предел не считается проверенным
    dialog._run.click()
    dialog._playback._button.click()
    assert dialog._playback._timer.isActive()
    assert "Неизвестные пределы не проверены" in dialog._playback._message.text()
    dialog._playback.advance()
    assert dialog._table.currentRow() == 1
    dialog._side.setCurrentIndex(1)
    assert not dialog._playback._timer.isActive() and dialog._table.rowCount() == 0
    assert not dialog._playback._button.isEnabled()


def test_playback_timer_fps_pause_and_close(window, qtbot):
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    window.controller.new_project("ring")
    dialog = AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._from.setValue(0)
    dialog._to.setValue(3)
    dialog._run.click()
    dialog._playback._fps.setValue(30)
    assert dialog._playback._timer.interval() == 33
    dialog._playback._button.click()
    qtbot.waitUntil(lambda: dialog._table.currentRow() > 0, timeout=3000)
    dialog._playback._button.click()
    assert not dialog._playback._timer.isActive()
    if dialog._table.currentRow() == 3:
        dialog._table.setCurrentCell(0, 0)
    dialog._playback._button.click()
    assert dialog._playback._timer.isActive()
    dialog.reject()
    assert not dialog._playback._timer.isActive()


def test_playback_combined_stops_before_either_side_limit(window, qtbot):
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog

    window.controller.new_project("ring")
    dialog = AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(2)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    dialog._show_damper.setChecked(True)
    dialog._damper_min.setValue(394)
    dialog._damper_max.setValue(450)
    dialog._run.click()
    assert dialog._playback_problem(0) is None
    assert dialog._playback_problem(1) == "обнаружен конфликт амортизатора"
    dialog._playback._button.click()
    dialog._playback.advance()
    assert dialog._table.currentRow() == 0 and not dialog._playback._timer.isActive()
    assert "конфликт амортизатора" in dialog._playback._message.text()
    dialog._damper_min.setValue(0)
    dialog._damper_max.setValue(0)
    dialog._run.click()
    dialog._playback._button.click()
    dialog._playback.advance()
    assert dialog._table.currentRow() == 1
    dialog._table.setCurrentCell(2, 0)  # ручной переход на конец ставит паузу
    assert not dialog._playback._timer.isActive()
    assert "конец таблицы" in dialog._playback._message.text()
    dialog._table.setCurrentCell(0, 0)
    dialog._playback._button.click()
    assert dialog._playback._timer.isActive()
    window.controller.new_project("city")
    assert not dialog._playback._timer.isActive() and dialog._preview.frame is None


def test_playback_stops_before_unsolved_row(window, qtbot, monkeypatch):
    from dataclasses import replace

    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.double_wishbone import KinematicsError
    from suspensionlab.core.sweep import SweepPoint
    from suspensionlab.ui import analysis_dialog

    window.controller.new_project("ring")
    dialog = analysis_dialog.AnalysisDialog(window.controller, window)
    qtbot.addWidget(dialog)
    dialog._from.setValue(0)
    dialog._to.setValue(1)
    original = analyze_corner(window.controller.project.front, window.controller.project.vehicle, [0, 1])
    failed = SweepPoint(1, None, KinematicsError(1, "test"))
    partial = replace(original, sweep=replace(original.sweep, points=(original.sweep.points[0], failed)),
                      samples=(original.samples[0], None))
    monkeypatch.setattr(analysis_dialog, "analyze_corner", lambda *args, **kwargs: partial)
    dialog._run.click()
    dialog._playback._button.click()
    dialog._playback.advance()
    assert dialog._table.currentRow() == 0 and dialog._preview.frame is not None
    assert not dialog._playback._timer.isActive()
    assert "нет рассчитанной схемы" in dialog._playback._message.text()


def test_corner_export_contains_displayed_rows_context_and_no_stale_results(window, qtbot, tmp_path, monkeypatch):
    import csv

    from suspensionlab.export.csv_report import write_csv_report
    from suspensionlab.ui import analysis_dialog

    c = window.controller
    c.new_project("ring")
    c.set_value(c.project.meta, "name", "=unsafe name")
    before = c.project.to_dict()
    dialog = analysis_dialog.AnalysisDialog(c, window)
    qtbot.addWidget(dialog)
    assert not dialog._export_button.isEnabled()
    dialog._from.setValue(-1)
    dialog._to.setValue(1)
    dialog._damper.setChecked(True)
    dialog._damping.setChecked(True)
    dialog._velocity.setText("20")
    dialog._compression.setText("2")
    dialog._rebound.setText("4")
    dialog._run.click()
    assert dialog._export_button.isEnabled()
    captured = []
    monkeypatch.setattr(analysis_dialog, "save_table_dialog", lambda _parent, report: captured.append(report))
    dialog._export_button.click()
    assert len(captured) == 1
    report = captured[0]
    metadata = dict(report.metadata)
    assert metadata["Название проекта"] == "=unsafe name"
    assert metadata["Есть несохранённые изменения проекта"] == "да"
    assert len(metadata["SHA-256 сериализуемой модели проекта"]) == 64
    assert metadata["Скорость колеса, мм/с"] == "20"
    assert metadata["Длина сжатого, мм (0 — неизвестна)"] == "не задано — не проверено"
    assert len(report.rows) == 3 and report.rows[1][1] == dialog._table.item(1, 1).text()
    path = write_csv_report(report, tmp_path / "corner.csv")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert ["Название проекта", "'=unsafe name"] in rows
    assert "экспериментальная" in metadata["Ограничения"].lower()
    assert "статус определяется до округления" in metadata["Точность"]
    assert "статус определяется до округления" in dialog._notice.text()
    assert c.project.to_dict() == before
    dialog._to.setValue(2)
    assert not dialog._export_button.isEnabled() and dialog._table.rowCount() == 0


def test_antiroll_export_preserves_assumptions_and_failures(window, qtbot, monkeypatch):
    from PySide6.QtWidgets import QLabel

    from suspensionlab.ui import antiroll_dialog

    window.controller.new_project("ring")
    dialog = antiroll_dialog.AntiRollDialog(window.controller, window)
    qtbot.addWidget(dialog)
    assert any("статус определяется до округления" in label.text() for label in dialog.findChildren(QLabel))
    dialog._from.setValue(0)
    dialog._to.setValue(1)
    dialog._axis_x.setText("-250")
    dialog._axis_z.setText("320")
    dialog._rate.setText("1000")
    dialog._show_spring.setChecked(True)
    dialog._spring_length.setValue(230)
    dialog._coil_bind.setValue(231)
    dialog._run.click()
    captured = []
    monkeypatch.setattr(antiroll_dialog, "save_table_dialog", lambda _parent, report: captured.append(report))
    dialog._export_button.click()
    assert len(captured) == 1
    report = captured[0]
    params = dict(report.metadata)
    assert "статус определяется до округления" in params["Точность"]
    assert params["Координата оси X, мм"] == "-250"
    assert params["Крутильная жёсткость, Н·м/рад"] == "1000"
    assert params["Длина смыкания, мм (0 — неизвестна)"] == "231.0"
    assert any("СМЫКАНИЕ ВИТКОВ" in field for row in report.rows for field in row)
    dialog._rate.setText("2000")
    assert not dialog._export_button.isEnabled() and dialog._table.rowCount() == 0


def test_csv_save_dialog_cancel_extension_and_io_error(window, tmp_path, monkeypatch):
    from suspensionlab.export.csv_report import CSVReport
    from suspensionlab.ui import table_export

    report = CSVReport((("Название", "пример"),), ("Ход",), (("1",),))
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    before = set(tmp_path.iterdir())
    table_export.save_table_dialog(window, report)
    assert set(tmp_path.iterdir()) == before
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: (str(tmp_path / "result"), ""))
    table_export.save_table_dialog(window, report)
    assert (tmp_path / "result.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    errors = []
    monkeypatch.setattr(table_export.QMessageBox, "warning", lambda *args: errors.append(args))
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: (str(tmp_path / "missing" / "file.csv"), ""))
    table_export.save_table_dialog(window, report)
    assert len(errors) == 1 and "Не удалось" in errors[0][2]


def test_save_and_autosave_failure_preserve_original_and_dirty_state(window, tmp_path, monkeypatch):
    from suspensionlab.model import project_io
    from suspensionlab.model.project_io import ProjectIOError
    from suspensionlab.ui import controller as module

    c = window.controller
    original = c.save_project(tmp_path / "project")
    original_bytes = original.read_bytes()
    backup = tmp_path / "autosave.susp.json"
    backup.write_bytes(b"old backup")
    monkeypatch.setattr(module, "autosave_path", lambda: backup)
    c.set_value(c.project.vehicle, "mass_kg", c.project.vehicle.mass_kg + 50)
    messages = []
    c.statusMessage.connect(messages.append)

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(project_io.os, "replace", fail)
    with pytest.raises(ProjectIOError):
        c.save_project()
    assert c.dirty and c.project.path == str(original) and original.read_bytes() == original_bytes
    assert not c.autosave()
    assert backup.read_bytes() == b"old backup"
    assert c.dirty and c.project.path == str(original) and messages[-1] == "autosave.failed"
    assert not list(tmp_path.glob(".suspensionlab-project-*.tmp"))


def test_autosave_directory_failure_is_reported(window, monkeypatch):
    from suspensionlab.ui import controller as module

    messages = []
    window.controller.statusMessage.connect(messages.append)

    def fail():
        raise OSError("directory unavailable")

    monkeypatch.setattr(module, "autosave_path", fail)
    assert not window.controller.autosave()
    assert messages[-1] == "autosave.failed"


def test_snapshot_restore_history_and_save_reload(window, tmp_path):
    c = window.controller
    c.new_project("ring")
    initial = c.project.vehicle.mass_kg
    c.add_snapshot("До изменений")
    c.set_value(c.project.vehicle, "mass_kg", initial + 100)
    c.set_lock("front.point.ubj.z", True)
    snapshots, locks, view = c.project.snapshots, c.project.locks, c.project.view
    c.select(Selection("point", "front", "ubj"))
    c.restore_snapshot(0)
    assert c.selection is None and c.dirty
    assert c.project.vehicle.mass_kg == initial
    assert c.project.snapshots is snapshots and c.project.locks is locks and c.project.view is view
    assert c.undo.undo_label_key() == "undo.restore_snapshot"
    c.undo_last()
    assert c.project.vehicle.mass_kg == initial + 100
    c.undo_last()
    assert not c.is_locked("front.point.ubj.z")
    c.undo_last()
    assert c.project.vehicle.mass_kg == initial
    c.redo_last()
    c.redo_last()
    c.redo_last()
    assert c.project.vehicle.mass_kg == initial and c.is_locked("front.point.ubj.z")
    path = c.save_project(tmp_path / "restored")
    c.open_project(path)
    assert c.project.vehicle.mass_kg == initial and c.project.snapshots[0].name == "До изменений"
    assert c.is_locked("front.point.ubj.z")


def test_snapshot_restore_invalid_preserves_history_and_selection(window):
    c = window.controller
    c.new_project("ring")
    c.add_snapshot("Повреждён")
    c.set_value(c.project.vehicle, "mass_kg", c.project.vehicle.mass_kg + 50)
    c.undo_last()
    assert c.undo.can_redo
    c.project.snapshots[0].data = {}
    c.select(Selection("vehicle"))
    before = c.project.to_dict()
    depth = c.undo.depth()
    with pytest.raises(ValueError):
        c.restore_snapshot(0)
    assert c.project.to_dict() == before and c.selection == Selection("vehicle")
    assert c.undo.depth() == depth and c.undo.can_redo
    with pytest.raises(ValueError):
        c.restore_snapshot(-1)
    c.redo_last()
    assert c.project.vehicle.mass_kg == before["vehicle"]["mass_kg"] + 50


def test_restore_snapshot_dialog_duplicate_names_and_empty(window, qtbot):
    from suspensionlab.ui.dialogs import RestoreSnapshotDialog

    c = window.controller
    c.new_project("ring")
    empty = RestoreSnapshotDialog(c.project, window)
    qtbot.addWidget(empty)
    assert not empty._restore.isEnabled() and empty.selected_index() == -1
    c.add_snapshot("Одинаковое")
    c.set_value(c.project.vehicle, "mass_kg", 2000)
    c.add_snapshot("Одинаковое")
    dialog = RestoreSnapshotDialog(c.project, window)
    qtbot.addWidget(dialog)
    assert dialog._list.item(0).text() == "1. Одинаковое"
    assert dialog._list.item(1).text() == "2. Одинаковое"
    dialog._list.setCurrentRow(1)
    assert dialog.selected_index() == 1 and dialog._restore.isEnabled()
    c.set_value(c.project.vehicle, "mass_kg", 2200)
    c.restore_snapshot(dialog.selected_index())
    assert c.project.vehicle.mass_kg == 2000


def test_snapshot_menu_cancel_and_invalid(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from suspensionlab.ui import main_window

    c = window.controller
    c.new_project("ring")
    c.add_snapshot("A")
    before = c.project.to_dict()

    class FakeDialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return 0

        def selected_index(self):
            return 0

    monkeypatch.setattr(main_window, "RestoreSnapshotDialog", FakeDialog)
    window.action_restore_snapshot.trigger()
    assert c.project.to_dict() == before
    c.project.snapshots[0].data = {}
    before = c.project.to_dict()
    FakeDialog.exec = lambda self: 1
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.action_restore_snapshot.trigger()
    assert len(warnings) == 1 and c.project.to_dict() == before


def test_snapshot_menu_applies_selected_entry_and_invalidates_results(window, qtbot, monkeypatch):
    from suspensionlab.ui import main_window
    from suspensionlab.ui.analysis_dialog import AnalysisDialog

    c = window.controller
    c.new_project("ring")
    baseline = c.project.vehicle.mass_kg
    c.add_snapshot("Начало")
    c.set_value(c.project.vehicle, "mass_kg", baseline + 100)
    analysis = AnalysisDialog(c, window)
    qtbot.addWidget(analysis)
    analysis._run.click()
    assert analysis._table.rowCount() > 0

    class FakeDialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return 1

        def selected_index(self):
            return 0

    monkeypatch.setattr(main_window, "RestoreSnapshotDialog", FakeDialog)
    window.action_restore_snapshot.trigger()
    assert c.project.vehicle.mass_kg == baseline and c.dirty
    assert analysis._table.rowCount() == 0
    assert window._stack.currentWidget() is window._tabs


def test_recover_autosave_is_detached_protected_and_resumes_after_save(window, tmp_path, monkeypatch):
    from suspensionlab.model.project_io import ProjectIOError, load_project
    from suspensionlab.ui import controller as module

    c = window.controller
    c.new_project("ring")
    original = c.save_project(tmp_path / "original")
    original_bytes = original.read_bytes()
    c.set_value(c.project.vehicle, "mass_kg", 1725.0)
    backup = tmp_path / "autosave.susp.json"
    monkeypatch.setattr(module, "autosave_path", lambda: backup)
    assert c.autosave()
    backup_bytes = backup.read_bytes()
    c.set_value(c.project.vehicle, "mass_kg", 1800.0)
    recovered, source = c.read_autosave()
    assert c.project.vehicle.mass_kg == 1800.0
    c.recover_autosave(recovered, source)
    assert c.project.vehicle.mass_kg == 1725.0
    assert c.dirty and c.recovery_pending and c.project.path is None
    assert "автосохранение приостановлено" in window.windowTitle()
    assert not c.undo.can_undo
    c.set_value(c.project.vehicle, "mass_kg", 1900.0)
    assert not c.autosave() and backup.read_bytes() == backup_bytes
    with pytest.raises(ProjectIOError) as error:
        c.save_project(backup)
    assert error.value.message_key == "autosave.protected"
    assert c.recovery_pending and c.dirty and c.project.path is None
    assert backup.read_bytes() == backup_bytes and original.read_bytes() == original_bytes
    result = c.save_project(tmp_path / "recovered")
    assert not c.recovery_pending and not c.dirty and c.project.path == str(result)
    assert load_project(result).vehicle.mass_kg == 1900.0
    assert backup.read_bytes() == backup_bytes
    c.set_value(c.project.vehicle, "mass_kg", 2000.0)
    assert c.autosave()
    assert load_project(backup).vehicle.mass_kg == 2000.0
    assert original.read_bytes() == original_bytes


def test_recovery_guard_blocks_saving_current_project_over_candidate(window, tmp_path, monkeypatch):
    from suspensionlab.model.project_io import ProjectIOError
    from suspensionlab.ui import controller as module

    c = window.controller
    backup = tmp_path / "autosave.susp.json"
    monkeypatch.setattr(module, "autosave_path", lambda: backup)
    c.save_project(backup)
    initial = backup.read_bytes()
    recovered, source = c.read_autosave()
    c.set_value(c.project.vehicle, "mass_kg", 1700.0)
    with c.guard_autosave(source):
        with pytest.raises(ProjectIOError) as error:
            c.save_project()
        assert error.value.message_key == "autosave.protected"
        assert not c.autosave()
        assert backup.read_bytes() == initial
    assert c.dirty and c.project.path == str(backup)
    assert recovered.vehicle.mass_kg != c.project.vehicle.mass_kg


def test_recovery_ui_cancel_bad_file_and_success(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from suspensionlab.ui import controller as module

    c = window.controller
    c.new_project("ring")
    backup = tmp_path / "autosave.susp.json"
    monkeypatch.setattr(module, "autosave_path", lambda: backup)
    assert c.autosave()
    before = c.project.to_dict()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.action_recover_autosave.trigger()
    assert c.project.to_dict() == before and not c.recovery_pending and window._autosave_timer.isActive()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    backup.write_text("{}", encoding="utf-8")
    errors = []
    monkeypatch.setattr(window, "_show_error", errors.append)
    window.action_recover_autosave.trigger()
    assert errors and c.project.to_dict() == before and not c.recovery_pending
    assert window._autosave_timer.isActive()
    assert c.autosave()
    monkeypatch.setattr(window, "_confirm_discard_changes", lambda: False)
    window.action_recover_autosave.trigger()
    assert c.project.to_dict() == before and not c.recovery_pending and window._autosave_timer.isActive()
    monkeypatch.setattr(window, "_confirm_discard_changes", lambda: True)
    window.action_recover_autosave.trigger()
    assert c.recovery_pending and c.dirty and c.project.path is None
    assert window._stack.currentWidget() is window._tabs and window._autosave_timer.isActive()


def test_recovery_save_failure_remains_protected(window, tmp_path, monkeypatch):
    from suspensionlab.model import project_io
    from suspensionlab.model.project_io import ProjectIOError
    from suspensionlab.ui import controller as module

    c = window.controller
    backup = tmp_path / "autosave.susp.json"
    monkeypatch.setattr(module, "autosave_path", lambda: backup)
    assert c.autosave()
    contents = backup.read_bytes()
    project, source = c.read_autosave()
    c.recover_autosave(project, source)

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(project_io.os, "replace", fail)
    with pytest.raises(ProjectIOError):
        c.save_project(tmp_path / "copy")
    assert c.dirty and c.project.path is None and c.recovery_pending
    assert not c.autosave() and backup.read_bytes() == contents


def test_recovery_rejects_alias_of_autosave_and_releases_on_new_project(window, tmp_path, monkeypatch):
    import os

    from suspensionlab.model.project_io import ProjectIOError
    from suspensionlab.ui import controller as module

    c = window.controller
    backup = tmp_path / "autosave.susp.json"
    monkeypatch.setattr(module, "autosave_path", lambda: backup)
    assert c.autosave()
    data = backup.read_bytes()
    project, source = c.read_autosave()
    c.recover_autosave(project, source)
    with pytest.raises(ProjectIOError):
        c.save_project(tmp_path / "autosave.json")
    alias = tmp_path / "alias.susp.json"
    try:
        os.link(backup, alias)
    except OSError:
        pass  # Файловая система или политика могут запрещать жёсткие ссылки.
    else:
        with pytest.raises(ProjectIOError) as error:
            c.save_project(alias)
        assert error.value.message_key == "autosave.protected"
    assert backup.read_bytes() == data
    c.new_project("ring")
    assert not c.recovery_pending


def test_equilibrium_dialog_matches_core_and_invalidates_stale_result(window, qtbot):
    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    c = window.controller
    c.new_project("ring")
    before = c.project.to_dict()
    load = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=150).evaluate(12, 1).wheel_support_n
    dialog = EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    dialog._length.setValue(230)
    dialog._bind.setValue(150)
    dialog._load.setValue(load)
    dialog._damper.setChecked(True)
    dialog._damper_min.setValue(300)
    dialog._damper_max.setValue(500)
    dialog._run.click()
    result = dialog._result
    assert result is not None and result.path is not None and result.path.completed
    assert result.estimate.travel_mm == pytest.approx(12, abs=0.1)
    assert result.upper.travel_mm - result.lower.travel_mm <= 0.1
    assert result.path.actual_step_mm <= 1
    assert "не доказательство" in dialog._status.text()
    assert "проверены в рассчитанных точках" in dialog._output.text()
    assert c.project.to_dict() == before
    dialog._side.setCurrentIndex(1)
    assert dialog._result is None and dialog._output.text() == ""
    dialog._run.click()
    assert dialog._result is not None
    assert dialog._result.estimate.travel_mm == pytest.approx(12, abs=0.1)
    c.set_value(c.project.vehicle, "mass_kg", c.project.vehicle.mass_kg + 1)
    assert dialog._result is None and dialog._output.text() == ""
    dialog._role.setCurrentIndex(1)
    assert not dialog._run.isEnabled()


def test_equilibrium_dialog_rejects_incomplete_inputs_and_conflicts(window, qtbot, caplog):
    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    c = window.controller
    c.new_project("ring")
    dialog = EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    dialog._run.click()
    assert "положительные" in dialog._status.text() and dialog._result is None
    dialog._length.setValue(230)
    dialog._load.setValue(1000)
    dialog._damper.setChecked(True)
    dialog._run.click()
    assert "обе" in dialog._status.text() and dialog._result is None
    dialog._damper_min.setValue(500)
    dialog._damper_max.setValue(300)
    dialog._run.click()
    assert "Расчёт не выполнен" in dialog._status.text()
    dialog._damper.setChecked(False)
    dialog._load.setValue(50000)
    dialog._run.click()
    assert "разные стороны" in dialog._status.text() and dialog._result is None
    dialog._bind.setValue(231)
    dialog._load.setValue(1000)
    dialog._run.click()
    assert "неопределённая сила" in dialog._status.text() and dialog._output.text() == ""
    # Концы интервала допустимы, но от статики путь не начинается безопасно.
    dialog._bind.setValue(230.1)
    dialog._from.setValue(-20)
    dialog._to.setValue(-10)
    load = SpringEquilibrium(c.project.front, 230).evaluate(-12, 1).wheel_support_n
    dialog._load.setValue(load)
    dialog._run.click()
    assert "Проверка пути не пройдена" in dialog._status.text()
    assert "0.000" in dialog._status.text() and dialog._result is None and dialog._output.text() == ""
    assert dialog._path is not None and dialog._path.failure is not None
    assert not dialog._path.samples and dialog._path_button.isEnabled() and not dialog._export_button.isEnabled()
    assert "Проверка пути баланса прервана" in caplog.text


def test_equilibrium_menu_opens_dialog(window, monkeypatch):
    from suspensionlab.ui import main_window

    calls = []

    class FakeDialog:
        def __init__(self, controller, parent):
            calls.append((controller, parent))

        def exec(self):
            calls.append("exec")

        def deleteLater(self):  # noqa: N802 (Qt API)
            calls.append("delete")

    monkeypatch.setattr(main_window, "EquilibriumDialog", FakeDialog)
    window.action_equilibrium.trigger()
    assert calls == [(window.controller, window), "exec", "delete"]


def test_equilibrium_csv_matches_visible_result_and_unknown_limits(window, qtbot, tmp_path, monkeypatch):
    import csv
    import json

    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.export.csv_report import write_csv_report
    from suspensionlab.ui import equilibrium_dialog

    c = window.controller
    c.new_project("ring")
    c.set_value(c.project.meta, "name", "=опасное имя")
    before = c.project.to_dict()
    load = SpringEquilibrium(c.project.front, 230).evaluate(12, 1).wheel_support_n
    dialog = equilibrium_dialog.EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    assert not dialog._export_button.isEnabled()
    dialog._length.setValue(230)
    dialog._load.setValue(load)
    dialog._run.click()
    assert dialog._export_button.isEnabled() and dialog._display_values is not None
    captured = []
    monkeypatch.setattr(equilibrium_dialog, "save_table_dialog", lambda _parent, report: captured.append(report))
    dialog._export_button.click()
    assert len(captured) == 1
    report = captured[0]
    meta, rows = dict(report.metadata), dict(report.rows)
    assert meta["Расчёт"] == "Условный баланс одной стороны"
    assert meta["Название проекта"] == "=опасное имя"
    assert meta["Есть несохранённые изменения проекта"] == "да"
    assert len(meta["SHA-256 сериализуемой модели проекта"]) == 64
    assert "непрерывная достижимость" in meta["Ограничения условного баланса"].lower()
    assert "не полная точность" in meta["Точность"]
    assert meta["Длина смыкания, мм (0 — неизвестна)"] == "не задано — не проверено"
    assert meta["Проверять упоры амортизатора на нижнем рычаге"] == "нет"
    assert meta["Длина сжатого амортизатора, мм"] == "не включено"
    assert json.loads(meta["Параметры пружины проекта (сериализованы, округлены)"]) == c.project.front.spring.to_dict()
    assert rows["Оценка середины хода, мм"] == dialog._display_values["travel"]
    assert rows["Невязка в оценке, Н"] == dialog._display_values["residual"]
    assert rows["Проверка смыкания пружины"] == rows["Проверка упоров амортизатора"] == "не заданы — не проверены"
    assert all(value in dialog._output.text() for value in dialog._display_values.values())
    target = write_csv_report(report, tmp_path / "баланс.csv")
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    with target.open(encoding="utf-8-sig", newline="") as handle:
        data = list(csv.reader(handle, delimiter=";"))
    assert ["Название проекта", "'=опасное имя"] in data
    assert ["Оценка середины хода, мм", dialog._display_values["travel"]] in data
    assert c.project.to_dict() == before
    dialog._side.setCurrentIndex(1)
    assert not dialog._export_button.isEnabled() and dialog._display_values is None
    dialog._export()
    assert len(captured) == 1


def test_equilibrium_csv_records_active_limits_and_invalidates_on_failure(window, qtbot, monkeypatch):
    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.ui import equilibrium_dialog

    c = window.controller
    c.new_project("ring")
    load = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=150).evaluate(12, 1).wheel_support_n
    dialog = equilibrium_dialog.EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    dialog._length.setValue(230)
    dialog._load.setValue(load)
    dialog._bind.setValue(150)
    dialog._damper.setChecked(True)
    dialog._damper_min.setValue(300)
    dialog._damper_max.setValue(500)
    dialog._run.click()
    captured = []
    monkeypatch.setattr(equilibrium_dialog, "save_table_dialog", lambda _parent, report: captured.append(report))
    dialog._export_button.click()
    report = captured[0]
    params, rows = dict(report.metadata), dict(report.rows)
    assert params["Длина смыкания, мм (0 — неизвестна)"] == "150.0"
    assert params["Проверять упоры амортизатора на нижнем рычаге"] == "да"
    assert params["Длина сжатого амортизатора, мм"] == "300.0"
    assert params["Длина разжатого амортизатора, мм"] == "500.0"
    assert rows["Проверка смыкания пружины"] == rows["Проверка упоров амортизатора"] == "проверены в рассчитанных точках"
    c.set_value(c.project.vehicle, "mass_kg", c.project.vehicle.mass_kg + 1)
    assert not dialog._export_button.isEnabled() and dialog._display_values is None
    dialog._run.click()
    assert dialog._export_button.isEnabled()
    dialog._from.setValue(30)
    dialog._to.setValue(-30)
    dialog._run.click()
    assert dialog._result is None and not dialog._export_button.isEnabled()
    dialog._export()
    assert len(captured) == 1


def test_equilibrium_csv_cancel_and_write_failure_preserve_existing_file(window, qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.export import csv_report
    from suspensionlab.ui import equilibrium_dialog, table_export

    c = window.controller
    c.new_project("ring")
    load = SpringEquilibrium(c.project.front, 230).evaluate(12, 1).wheel_support_n
    dialog = equilibrium_dialog.EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    dialog._length.setValue(230)
    dialog._load.setValue(load)
    dialog._run.click()
    assert dialog._export_button.isEnabled()
    before = c.project.to_dict()
    target = tmp_path / "result.csv"
    target.write_bytes(b"previous")
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    dialog._export_button.click()
    assert target.read_bytes() == b"previous"
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(csv_report.os, "replace", fail)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog._export_button.click()
    assert len(warnings) == 1 and target.read_bytes() == b"previous"
    assert not list(tmp_path.glob(".suspensionlab-*.tmp"))
    assert c.project.to_dict() == before and dialog._export_button.isEnabled()


def test_equilibrium_path_view_shows_exact_computed_samples_and_invalidates(window, qtbot):
    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.export.equilibrium_path import PATH_COLUMNS, format_path_sample
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    c = window.controller
    c.new_project("ring")
    before = c.project.to_dict()
    load = SpringEquilibrium(c.project.front, 230).evaluate(-12, 1).wheel_support_n
    dialog = EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    assert not dialog._path_button.isEnabled()
    dialog._length.setValue(230)
    dialog._load.setValue(load)
    dialog._run.click()
    assert dialog._path_button.isEnabled() and dialog._path is not None and dialog._path.completed
    path = dialog._path
    view = EquilibriumPathDialog(path, dialog)
    qtbot.addWidget(view)
    assert "все запрошенные точки" in view._status.text()
    assert view._table.rowCount() == len(path.samples) and view._table.columnCount() == len(PATH_COLUMNS)
    assert path.samples[0].travel_mm == 0 and path.samples[-1].travel_mm < 0
    for i in (0, len(path.samples) - 1):
        assert tuple(view._table.item(i, col).text() for col in range(len(PATH_COLUMNS))) == format_path_sample(path.samples[i])
    assert c.project.to_dict() == before
    dialog._length.setValue(231)
    assert dialog._path is None and not dialog._path_button.isEnabled()
    dialog._run.click()
    assert dialog._path_button.isEnabled()
    c.set_value(c.project.vehicle, "mass_kg", c.project.vehicle.mass_kg + 1)
    assert dialog._path is None and not dialog._path_button.isEnabled()


def test_equilibrium_path_failed_prefix_and_zero_samples(window, qtbot):
    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    axle = window.controller.project.front
    path = SpringEquilibrium(axle, 230, coil_bind_length_mm=225).check_path(30, 1000, step_mm=5)
    assert path.failure is not None and len(path.samples) > 0
    view = EquilibriumPathDialog(path, window)
    qtbot.addWidget(view)
    assert "ПРОВЕРКА НЕ ПРОЙДЕНА" in view._status.text()
    assert "Результат баланса не выдан" in view._status.text()
    assert f"{path.failure.failure_travel_mm:.4f}" in view._status.text()
    assert view._table.rowCount() == len(path.samples)
    failed_initial = SpringEquilibrium(axle, 230, coil_bind_length_mm=231).check_path(20, 1000, step_mm=5)
    assert failed_initial.failure is not None and not failed_initial.samples
    empty = EquilibriumPathDialog(failed_initial, window)
    qtbot.addWidget(empty)
    assert "ПРОВЕРКА НЕ ПРОЙДЕНА" in empty._status.text() and empty._table.rowCount() == 0


def test_equilibrium_failure_path_access_and_branch_mismatch(window, qtbot, monkeypatch):
    from dataclasses import replace

    from suspensionlab.core.equilibrium import EquilibriumPathError, PathFailure, SpringEquilibrium
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    c = window.controller
    c.new_project("ring")
    system = SpringEquilibrium(c.project.front, 230)
    path = system.check_path(5, 1000)
    mismatch = PathFailure(5, 5, "branch_mismatch", "ветвь решения не совпадает")
    failed = replace(path, failure=mismatch)

    def fail(*args, **kwargs):
        raise EquilibriumPathError(failed)

    monkeypatch.setattr(SpringEquilibrium, "find", fail)
    dialog = EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    dialog._length.setValue(230)
    dialog._load.setValue(1000)
    dialog._run.click()
    assert dialog._result is None and not dialog._export_button.isEnabled()
    assert dialog._path is failed and dialog._path_button.isEnabled()
    view = EquilibriumPathDialog(failed, dialog)
    qtbot.addWidget(view)
    assert "ПРОВЕРКА НЕ ПРОЙДЕНА" in view._status.text() and "несовпадение ветвей" in view._status.text()
    assert view._table.rowCount() == len(failed.samples)
    dialog._bind.setValue(150)
    assert dialog._path is None and not dialog._path_button.isEnabled()


def test_equilibrium_open_path_closes_when_project_changes(window, qtbot, monkeypatch):
    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.ui import equilibrium_dialog

    c = window.controller
    c.new_project("ring")
    load = SpringEquilibrium(c.project.front, 230).evaluate(12, 1).wheel_support_n
    dialog = equilibrium_dialog.EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    dialog._length.setValue(230)
    dialog._load.setValue(load)
    dialog._run.click()
    events = []

    class FakeView:
        def __init__(self, path, parent, **kwargs):
            events.append((path, parent))

        def exec(self):
            c.set_value(c.project.vehicle, "mass_kg", c.project.vehicle.mass_kg + 1)

        def reject(self):
            events.append("rejected")

        def deleteLater(self):  # noqa: N802 (Qt API)
            events.append("deleted")

    monkeypatch.setattr(equilibrium_dialog, "EquilibriumPathDialog", FakeView)
    dialog._path_button.click()
    assert events[-2:] == ["rejected", "deleted"]
    assert dialog._path is None and dialog._path_dialog is None and not dialog._path_button.isEnabled()


def test_equilibrium_path_csv_success_matches_table_and_context(window, qtbot, tmp_path, monkeypatch):
    import csv

    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.export.csv_report import write_csv_report
    from suspensionlab.ui import equilibrium_path_dialog
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    c = window.controller
    c.new_project("ring")
    c.set_value(c.project.meta, "name", "=небезопасно")
    before = c.project.to_dict()
    load = SpringEquilibrium(c.project.front, 230).evaluate(-12, 1).wheel_support_n
    dialog = EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    dialog._length.setValue(230)
    dialog._load.setValue(load)
    dialog._run.click()
    assert dialog._path is not None and dialog._path.completed
    path = dialog._path
    view = equilibrium_path_dialog.EquilibriumPathDialog(path, dialog,
                                                        report_factory=lambda table: dialog._path_report(path, table))
    qtbot.addWidget(view)
    captured = []
    monkeypatch.setattr(equilibrium_path_dialog, "save_table_dialog", lambda _parent, report: captured.append(report))
    assert view._export_button.isEnabled()
    view._export_button.click()
    report = captured[0]
    meta = dict(report.metadata)
    assert meta["Итог проверки пути"] == "Все запрошенные точки проверены — непрерывность не доказана"
    assert meta["Количество рассчитанных точек пути"] == str(len(path.samples))
    assert meta["Тип отказа пути"] == "—" and meta["Причина отказа пути"] == "—"
    assert meta["Длина смыкания, мм (0 — неизвестна)"] == "не задано — не проверено"
    assert meta["Проверять упоры амортизатора на нижнем рычаге"] == "нет"
    assert meta["Есть несохранённые изменения проекта"] == "да"
    assert len(meta["SHA-256 сериализуемой модели проекта"]) == 64
    assert "не доказаны" in meta["Ограничения проверки пути"]
    assert len(report.rows) == view._table.rowCount() == len(path.samples)
    assert report.columns == tuple(view._table.horizontalHeaderItem(i).text() for i in range(view._table.columnCount()))
    for row in range(view._table.rowCount()):
        assert report.rows[row] == tuple(view._table.item(row, col).text() for col in range(view._table.columnCount()))
    target = write_csv_report(report, tmp_path / "path.csv")
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert ["Название проекта", "'=небезопасно"] in rows
    assert list(report.columns) in rows and list(report.rows[-1]) in rows
    assert c.project.to_dict() == before
    dialog._side.setCurrentIndex(1)
    with pytest.raises(ValueError):
        dialog._path_report(path, view._table)


@pytest.mark.parametrize("scenario", ["partial", "empty", "branch"])
def test_equilibrium_path_csv_failure_is_explicit_even_when_empty(window, qtbot, monkeypatch, scenario):
    from dataclasses import replace

    from suspensionlab.core.equilibrium import EquilibriumPathError, PathFailure, SpringEquilibrium
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    c = window.controller
    c.new_project("ring")
    if scenario == "partial":
        path = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=225).check_path(30, 1000, step_mm=5)
        assert path.failure is not None and len(path.samples) > 0
    elif scenario == "empty":
        path = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=231).check_path(20, 1000, step_mm=5)
        assert path.failure is not None and not path.samples
    else:
        passed = SpringEquilibrium(c.project.front, 230).check_path(5, 1000)
        path = replace(passed, failure=PathFailure(5, 5, "branch_mismatch", "=опасная причина"))

    def fail(*args, **kwargs):
        raise EquilibriumPathError(path)

    monkeypatch.setattr(SpringEquilibrium, "find", fail)
    dialog = EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    dialog._length.setValue(230)
    dialog._load.setValue(1000)
    dialog._run.click()
    assert dialog._result is None and dialog._path is path and not dialog._export_button.isEnabled()
    view = EquilibriumPathDialog(path, dialog, report_factory=lambda table: dialog._path_report(path, table))
    qtbot.addWidget(view)
    report = dialog._path_report(path, view._table)
    meta = dict(report.metadata)
    assert meta["Итог проверки пути"] == "НЕ ПРОЙДЕНА — результат баланса не выдан"
    assert meta["Количество рассчитанных точек пути"] == str(len(path.samples))
    assert path.failure is not None
    assert meta["Ход отказа, мм"] == f"{path.failure.failure_travel_mm:.4f}"
    assert meta["Запрошенный ход при отказе, мм"] == f"{path.failure.requested_travel_mm:.4f}"
    assert meta["Причина отказа пути"] == path.failure.reason
    assert len(report.rows) == len(path.samples)
    if scenario == "branch":
        assert meta["Тип отказа пути"] == "несовпадение ветвей"
    if scenario == "empty":
        assert not report.rows and len(report.columns) > 0 and view._export_button.isEnabled()


def test_path_csv_cancel_and_write_failure_preserve_existing_file(window, qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.export import csv_report
    from suspensionlab.ui import table_export
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog
    from suspensionlab.ui.equilibrium_path_dialog import EquilibriumPathDialog

    c = window.controller
    c.new_project("ring")
    load = SpringEquilibrium(c.project.front, 230).evaluate(12, 1).wheel_support_n
    dialog = EquilibriumDialog(c, window)
    qtbot.addWidget(dialog)
    dialog._length.setValue(230)
    dialog._load.setValue(load)
    dialog._run.click()
    assert dialog._path is not None
    path = dialog._path
    view = EquilibriumPathDialog(path, dialog, report_factory=lambda table: dialog._path_report(path, table))
    qtbot.addWidget(view)
    before = c.project.to_dict()
    target = tmp_path / "path.csv"
    target.write_bytes(b"old")
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    view._export_button.click()
    assert target.read_bytes() == b"old"
    monkeypatch.setattr(table_export.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(csv_report.os, "replace", fail)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    view._export_button.click()
    assert len(warnings) == 1 and target.read_bytes() == b"old"
    assert not list(tmp_path.glob(".suspensionlab-*.tmp")) and c.project.to_dict() == before
