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
    assert dialog._front_drive.isChecked() and not dialog._rear_drive.isChecked()
    dialog._rear.setCurrentIndex(dialog._rear.findData("torsion_beam_rear"))
    assert not dialog._rear_drive.isEnabled() and not dialog._rear_drive.isChecked()
    project = dialog.selected_project()
    assert project is not None and project.rear.type_code == "torsion_beam_rear"
    window.controller.new_project(project=project)
    window._show_workspace()
    for mode in ("front", "side", "top"):
        window._canvases["both"].set_view_mode(mode)
        window._canvases["both"].grab()
    path = window.controller.save_project(tmp_path / "configured")
    window.controller.open_project(path)
    assert window.controller.project.front.type_code == "macpherson_front"
    dialog._list.setCurrentRow(1)
    assert dialog._front.currentData() == "multilink_front"
    assert dialog._front_drive.isChecked() and dialog._rear_drive.isChecked()
    dialog._rear.setCurrentIndex(dialog._rear.findData("live_axle_coil"))
    assert dialog.selected_project().rear.type_code == "live_axle_coil"
    dialog._list.setCurrentRow(2)
    assert dialog.selected_project() is None and dialog.selected_key() == "ring"


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


def test_analysis_dialog_shows_partial_failure_and_mechanical_conflicts(window, qtbot, monkeypatch):
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


def test_antiroll_dialog_input_validation_and_failure(window, qtbot, monkeypatch):
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
