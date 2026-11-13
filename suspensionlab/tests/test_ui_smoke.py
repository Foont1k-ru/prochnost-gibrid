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
