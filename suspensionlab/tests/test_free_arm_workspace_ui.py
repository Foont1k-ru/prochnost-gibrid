"""Collapsible independent-arm workspace preserves editing and CAD freshness."""
import pytest
from PySide6.QtCore import Qt
from test_free_arm_housing_ui import dialog_with_housing
from test_free_arm_ui import fill

from suspensionlab.ui.free_arm_dialog import FreeArmDialog


def test_settings_toggle_expands_workspace_without_discarding_input(qtbot, monkeypatch):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.show()
    fill(dialog)
    dialog.apply_fields()
    draft, document = dialog.draft, dialog._cad._document
    width = dialog._tabs.width()
    dialog._fields['front_X'].setText('3.5')
    assert dialog._cad._document is None
    dialog._settings_toggle.setChecked(False)
    qtbot.waitUntil(lambda: not dialog._parameters_scroll.isVisible())
    qtbot.waitUntil(lambda: dialog._tabs.width() > width)
    assert dialog._fields['front_X'].text() == '3.5' and dialog.draft is draft
    assert not dialog._save.isEnabled()
    dialog._settings_toggle.setChecked(True)
    assert dialog._parameters_scroll.isVisible() and dialog._fields['front_X'].text() == '3.5'
    dialog._restore_draft()
    assert dialog.draft is draft and dialog._cad._document == document and dialog._save.isEnabled()
    dialog.close()


def test_workspace_panels_toggle_independently(qtbot, monkeypatch):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.show()
    dialog._tabs.setCurrentWidget(dialog._cad)
    assert dialog._parameters_scroll.isVisible() and dialog._cad._quality.isVisible()
    dialog._settings_toggle.setChecked(False)
    assert not dialog._parameters_scroll.isVisible() and dialog._cad._quality.isVisible()
    dialog._advanced_toggle.setChecked(False)
    assert not dialog._parameters_scroll.isVisible() and not dialog._cad._quality.isVisible()
    dialog._settings_toggle.setChecked(True)
    assert dialog._parameters_scroll.isVisible() and not dialog._cad._quality.isVisible()
    dialog._advanced_toggle.setChecked(True)
    assert dialog._parameters_scroll.isVisible() and dialog._cad._quality.isVisible()
    dialog.close()


def test_projection_controls_only_occupy_space_when_needed(qtbot, monkeypatch):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.show()
    assert not dialog._projection_controls.isVisible()
    qtbot.waitUntil(lambda: dialog._tabs.height() > 0)
    height_3d = dialog._tabs.height()
    for canvas in dialog._projections:
        dialog._tabs.setCurrentWidget(canvas)
        assert dialog._projection_controls.isVisible()
    qtbot.waitUntil(lambda: dialog._tabs.height() < height_3d)
    dialog._tabs.setCurrentWidget(dialog._cad)
    assert not dialog._projection_controls.isVisible()
    qtbot.waitUntil(lambda: dialog._tabs.height() == height_3d)
    dialog.close()


@pytest.mark.parametrize('finish', ['cancel', 'stale_apply'])
def test_projection_controls_keep_cancel_accessible_if_tab_forced(qtbot, monkeypatch, finish):
    dialog, data = dialog_with_housing(qtbot, monkeypatch, ('front',))
    canvas = dialog._projections[0]
    dialog._tabs.setCurrentWidget(canvas)
    dialog._projection_point(canvas, 'bend_front')
    assert dialog._projection_session is not None
    dialog._projection_radius.setText('25')
    dialog._tabs.setCurrentWidget(dialog._cad)  # Disabled to users, but code can still change it.
    assert dialog._tabs.currentWidget() is dialog._cad
    assert dialog._projection_controls.isVisible() and dialog._projection_cancel.isEnabled()
    if finish == 'cancel':
        qtbot.mouseClick(dialog._projection_cancel, Qt.MouseButton.LeftButton)
    else:
        dialog._apply_projection_radius()
    assert dialog.draft == data.arm and dialog.housing == data.housing and dialog._projection_session is None
    assert not dialog._projection_controls.isVisible() and dialog._parameter_panel.isEnabled()
    dialog.close()


def test_projection_session_survives_view_toggles_without_unlocking_form(qtbot, monkeypatch):
    dialog, data = dialog_with_housing(qtbot, monkeypatch, ('front',))
    canvas = dialog._projections[0]
    dialog._tabs.setCurrentWidget(canvas)
    dialog._projection_point(canvas, 'bend_front')
    session = dialog._projection_session
    assert session is not None and not dialog._parameter_panel.isEnabled()
    dialog._projection_radius.setText('25')
    dialog._settings_toggle.setChecked(False)
    dialog._settings_toggle.setChecked(True)
    dialog._advanced_toggle.setChecked(False)
    dialog._advanced_toggle.setChecked(True)
    assert dialog._projection_session is session and dialog._projection_radius.text() == '25'
    assert not dialog._parameter_panel.isEnabled() and not dialog._save.isEnabled()
    qtbot.keyClick(dialog._projection_radius, Qt.Key.Key_Return)
    assert dialog.draft.front_bend.radius_mm == 25 and dialog.housing == data.housing
    assert dialog._parameter_panel.isEnabled() and dialog._save.isEnabled()
    dialog.close()


def test_compact_controls_keep_live_cad_and_inline_session(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, data = dialog_with_housing(qtbot, monkeypatch, ('front',))
    dialog._tabs.setCurrentWidget(dialog._cad)
    panel = dialog._cad
    panel._quality.setCurrentIndex(1)
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    mesh, generation = panel._view.mesh, panel.generation
    assert panel._parts_panel.isVisible() and panel._quality.isVisible()
    dialog._advanced_toggle.setChecked(False)
    assert not panel._parts_panel.isVisible() and not panel._quality.isVisible()
    assert panel._enable.isVisible() and panel._retry.isVisible()
    assert panel.generation == generation and panel._view.mesh is mesh
    dialog._open_inline_sketch('front')
    session = dialog._inline_session
    assert session is not None and dialog._inline_sketch.isVisible()
    dialog._inline_sketch.fields['R'].setText('25')
    dialog._settings_toggle.setChecked(False)
    dialog._advanced_toggle.setChecked(True)
    assert dialog._inline_session is session and not panel._parts_tree.isEnabled()
    assert dialog._inline_sketch.fields['R'].text() == '25' and panel._view.mesh is mesh
    dialog._inline_sketch._apply()
    assert dialog.draft.front_bend.radius_mm == 25 and dialog.housing == data.housing
    assert panel._view.mesh is None and panel._parts_tree.isEnabled()
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    assert panel._parts_panel.isVisible() and panel._quality.isVisible()
    dialog.close()
