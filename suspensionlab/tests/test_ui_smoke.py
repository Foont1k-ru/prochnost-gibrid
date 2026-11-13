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
