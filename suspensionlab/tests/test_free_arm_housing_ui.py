"""End-to-end independent housing: form, versions, views, freshness and CAD."""
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMenu
from test_free_arm_housing_io import make_draft
from test_free_arm_ui import fill

from suspensionlab.model.free_arm import FreeArmBend
from suspensionlab.model.free_arm_housing import FreeArmHousingDraft, FreeArmHousingError
from suspensionlab.model.free_arm_housing_io import read_free_arm_housing
from suspensionlab.model.free_arm_io import read_free_arm, write_free_arm
from suspensionlab.ui.free_arm_dialog import FreeArmDialog
from suspensionlab.ui.main_window import MainWindow


def dialog_with_housing(qtbot, monkeypatch, bent=()):
    data = make_draft(bent)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(data.arm)
    dialog._set_housing_fields(data.housing)
    dialog.show()
    dialog.apply_fields()
    assert dialog.draft == data.arm and dialog.housing == data.housing
    return dialog, data


def test_form_preview_save_open_restore_and_v1_compatibility(qtbot, monkeypatch, tmp_path):
    dialog, data = dialog_with_housing(qtbot, monkeypatch, ('front', 'rear'))
    paths = data.centerlines()
    assert dialog._cad._document['version'] == '2'
    assert dialog._projections[0].preview.centerlines == paths
    assert ('lbj', data.arm.outer_mm) in dialog._projections[0].points
    assert ('ball_housing_center', paths[0][-1]) in dialog._projections[0].points
    assert ('ball_housing_center', paths[0][-1]) in dialog._scene.frame.points
    path = tmp_path / 'v2.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_free_arm_housing(path) == data
    dialog._fields['housing_offset_X'].setText('40')
    assert not dialog._save.isEnabled() and dialog._cad._document is None
    dialog._restore_draft()
    assert dialog.housing == data.housing and dialog._cad._document['ball_housing']['offset_mm'][0] == 10
    dialog._housing_check.setChecked(False)
    dialog.apply_fields()
    assert dialog.housing is None and dialog._cad._document['version'] == '1'
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert dialog.draft == data.arm and dialog.housing == data.housing and dialog._housing_check.isChecked()
    assert dialog._projections[0].preview.centerlines == paths
    old_path = write_free_arm(tmp_path / 'v1.slarm', data.arm)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(old_path), ''))
    dialog._open_file()
    assert dialog.draft == read_free_arm(old_path) and dialog.housing is None
    assert not dialog._housing_check.isChecked() and dialog._cad._document['version'] == '1'
    dialog.close()


@pytest.mark.parametrize('key,value', [('housing_outer', 'nan'), ('housing_bore', '120'),
                                       ('housing_axis_Z', '0'), ('housing_offset_X', '-300')])
def test_invalid_housing_does_not_replace_accepted(qtbot, monkeypatch, key, value):
    dialog, data = dialog_with_housing(qtbot, monkeypatch)
    if key == 'housing_offset_X':
        for axis, number in zip('XYZ', (-300, -100, -10), strict=True):
            dialog._fields['housing_offset_' + axis].setText(str(number))
    else:
        dialog._fields[key].setText(value)
    assert dialog._cad._document is None and not dialog._save.isEnabled()
    dialog.apply_fields()
    assert dialog.draft == data.arm and dialog.housing == data.housing
    assert 'не применены' in dialog._status.text() and dialog._cad._document is None
    dialog._restore_draft()
    assert dialog._cad._document['version'] == '2' and dialog._save.isEnabled()
    dialog.close()


def test_save_dialog_race_does_not_write_or_discard_edit(qtbot, monkeypatch, tmp_path):
    dialog, data = dialog_with_housing(qtbot, monkeypatch)
    target = tmp_path / 'race.slarm'
    def change_during_dialog(*_):
        dialog._fields['housing_offset_X'].setText('11')
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', change_during_dialog)
    dialog._save_file()
    assert not target.exists() and dialog.housing == data.housing
    assert dialog._fields['housing_offset_X'].text() == '11' and dialog._cad._document is None
    dialog.close()


def test_housing_never_modifies_open_project(qtbot, monkeypatch, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    before = deepcopy(window.controller.project.to_dict())
    window.action_free_arm.trigger()
    dialog = window._free_arm_dialog
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    fill(dialog)
    dialog._housing_check.setChecked(True)
    dialog.apply_fields()
    path = tmp_path / 'independent.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_free_arm_housing(path).arm == dialog.draft
    assert window.controller.project.to_dict() == before and window.action_fixed_arm_skeleton.isEnabled()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert window.controller.project.to_dict() == before
    dialog.close()
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.close()


def test_projection_edit_keeps_housing_and_shifted_axis(qtbot, monkeypatch):
    dialog, data = dialog_with_housing(qtbot, monkeypatch, ('front',))
    canvas = dialog._projections[0]
    original_housing = dialog.housing
    dialog._tabs.setCurrentWidget(canvas)
    dialog._projection_point(canvas, 'bend_front')
    assert dialog._projection_session is not None
    dialog._projection_radius.setText('25')
    dialog._apply_projection_radius()
    assert dialog.draft.front_bend.radius_mm == 25 and dialog.housing is original_housing
    result = FreeArmHousingDraft(dialog.draft, dialog.housing)
    assert canvas.preview.centerlines == result.centerlines()
    assert dialog._cad._document['ball_housing'] == data.housing.as_data()
    dialog.close()


def test_projection_new_vertex_uses_shifted_end(qtbot, monkeypatch):
    dialog, data = dialog_with_housing(qtbot, monkeypatch)
    canvas = dialog._projections[0]
    dialog._tabs.setCurrentWidget(canvas)
    start, end = data.centerlines()[0]
    point = tuple((a + b) / 2 for a, b in zip(start, end, strict=True))
    dialog._projection_segment(canvas, 'front', point)
    assert dialog._projection_session is not None and dialog._projection_session.new_vertex == point
    assert dialog.draft == data.arm and dialog.housing == data.housing
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (20., True))
    dialog._apply_projection_candidate(canvas, 'bend_front', canvas.axes, point)
    assert dialog.draft == data.arm and dialog._projection_session is not None
    assert 'не достигает центра' in canvas._dimension_error.text()
    shifted = (point[0], point[1] + 15, point[2])
    dialog._apply_projection_candidate(canvas, 'bend_front', canvas.axes, shifted)
    assert dialog.draft.front_bend.vertex_mm == shifted and dialog.housing == data.housing
    assert canvas.preview.centerlines == FreeArmHousingDraft(dialog.draft, dialog.housing).centerlines()
    dialog.close()


def test_real_cad_context_edit_stale_and_failed_contact(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, data = dialog_with_housing(qtbot, monkeypatch, ('front',))
    dialog._tabs.setCurrentWidget(dialog._cad)
    panel = dialog._cad
    panel._quality.setCurrentIndex(1)
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    assert panel._view.mesh.part_names == ('tube_front', 'tube_rear', 'ball_housing')
    assert panel._parts_tree.topLevelItem(0).childCount() == 3
    mesh = panel._view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('ball_housing'))[0])
    dialog._settings_toggle.setChecked(False)
    assert not dialog._parameters_scroll.isVisible()

    def choose():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text() == 'Параметры центрального корпуса')
        qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())

    QTimer.singleShot(50, choose)
    with monkeypatch.context() as patch:
        patch.setattr(panel._view, '_pick_index', lambda *_args: index)
        qtbot.mouseClick(panel._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert dialog._settings_toggle.isChecked() and dialog._parameters_scroll.isVisible()
    assert QApplication.focusWidget() is dialog._fields['housing_outer']
    dialog._fields['housing_offset_X'].setText('11')
    assert panel._view.mesh is None and panel._document is None and not dialog._save.isEnabled()
    dialog.apply_fields()
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    assert panel._document['ball_housing']['offset_mm'][0] == 11 and panel._view.mesh is not mesh
    # Valid parameters but a CAD contact that cannot be built: never leave old mesh shown.
    dialog._fields['housing_length'].setText('5')
    dialog.apply_fields()
    assert panel._view.mesh is None
    qtbot.waitUntil(lambda: panel._worker is None and panel._retry.isEnabled() and not panel._ready, timeout=30000)
    assert panel._view.mesh is None and 'не построены' in panel._status.text()
    assert dialog.housing == replace(data.housing, offset_mm=(11., -30., 12.), length_mm=5.)
    dialog.close()


def test_housing_context_ignores_change_while_menu_is_open(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, data = dialog_with_housing(qtbot, monkeypatch)
    dialog._tabs.setCurrentWidget(dialog._cad)
    panel = dialog._cad
    panel._quality.setCurrentIndex(1)
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    mesh = panel._view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('ball_housing'))[0])

    def change_and_choose():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text() == 'Параметры центрального корпуса')
        dialog._fields['housing_offset_X'].setText('11')
        qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())

    QTimer.singleShot(50, change_and_choose)
    with monkeypatch.context() as patch:
        patch.setattr(panel._view, '_pick_index', lambda *_args: index)
        qtbot.mouseClick(panel._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert panel._view.mesh is None and panel._document is None and dialog.housing == data.housing
    assert QApplication.focusWidget() is not dialog._fields['housing_outer']
    dialog.close()


def test_housing_change_during_real_worker_never_shows_old_result(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, data = dialog_with_housing(qtbot, monkeypatch, ('front', 'rear'))
    dialog._tabs.setCurrentWidget(dialog._cad)
    panel = dialog._cad
    panel._quality.setCurrentIndex(1)
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._worker is not None, timeout=10000)
    token = panel.generation
    dialog._fields['housing_offset_X'].setText('11')
    dialog.apply_fields()
    assert panel.generation > token and panel._view.mesh is None
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    assert panel._document['ball_housing']['offset_mm'][0] == 11
    assert panel._is_current(panel._document) and panel._view.mesh is not None
    assert dialog.housing == replace(data.housing, offset_mm=(11., -30., 12.))
    dialog._fields['housing_offset_X'].setText('12')
    dialog.apply_fields()
    qtbot.waitUntil(lambda: panel._worker is not None, timeout=10000)
    dialog.close()
    assert panel._closed and (panel._worker is None or not panel._worker.isRunning())


def test_real_inline_sketch_edits_bend_without_losing_housing(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, data = dialog_with_housing(qtbot, monkeypatch, ('front',))
    dialog._tabs.setCurrentWidget(dialog._cad)
    panel = dialog._cad
    panel._quality.setCurrentIndex(1)
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    dialog._open_inline_sketch('front')
    assert dialog._inline_session is not None
    assert panel._view._sketch_path[-1] == pytest.approx(data.centerlines()[0][-1])
    dialog._inline_sketch.fields['R'].setText('25')
    dialog._inline_sketch._apply()
    assert dialog.draft.front_bend.radius_mm == 25 and dialog.housing == data.housing
    assert panel._document['version'] == '2' and panel._document['ball_housing'] == data.housing.as_data()
    qtbot.waitUntil(lambda: panel._ready and panel._worker is None, timeout=30000)
    # This bend is valid relative to the anchor but collinear with the shifted center.
    before = dialog.draft
    invalid = replace(before, front_bend=FreeArmBend((155, 35, 11), 20))
    with pytest.raises(FreeArmHousingError):
        FreeArmHousingDraft(invalid, dialog.housing)
    dialog._open_inline_sketch('front')
    dialog._apply_inline_sketch((155, 35, 11, 20))
    assert dialog.draft is before and dialog._inline_session is not None
    assert 'Не применено' in dialog._inline_sketch.status.text()
    dialog._close_inline_sketch()
    dialog.close()
