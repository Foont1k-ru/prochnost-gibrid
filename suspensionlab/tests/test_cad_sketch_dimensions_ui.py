"""Draft dimension labels are view overlays and never stale surface picks."""
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from test_fixed_arm_inline_sketch_ui import ready_editor
from test_free_arm_inline_ui import ready_dialog

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.ui.canvas.cad_preview import CadPreview


def view_with_overlay(qtbot):
    view = CadPreview()
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    view.set_mesh(CadMesh(np.array([[[0, 0, 0], [0, 200, 0], [300, 100, 10]]]), 1))
    view.set_sketch_overlay(((0, 0, 0), (150, 20, 50), (300, 100, 10)), (150, 20, 50),
                            dimensions=(150, 20, 50, 20))
    view.grab()
    assert set(view._sketch_dimension_rects) == {'X', 'Y', 'Z', 'R'}
    return view


def test_labels_follow_camera_and_ignore_stale_clicks(qtbot):
    view = view_with_overlay(qtbot)
    requested = []
    view.sketch_dimension_requested.connect(requested.append)
    pos = view._sketch_dimension_rects['R'].center().toPoint()
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=pos)
    assert requested == ['R']
    old = view._sketch_dimension_rects['X'].center().toPoint()
    view.yaw += .8  # Before the repaint the old clickable rectangle must not be used.
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=old)
    assert requested == ['R']
    view.grab()
    assert view._sketch_dimension_stamp == view._dimension_stamp()
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=view._sketch_dimension_rects['X'].center().toPoint())
    assert requested == ['R', 'X']
    view.set_sketch_overlay()
    assert not view._sketch_dimension_rects and view._sketch_dimension_stamp is None
    view.grab()
    assert not view._sketch_dimension_rects


def test_labels_hide_when_offscreen_or_occluded_by_controls(qtbot):
    view = view_with_overlay(qtbot)
    blocker = QWidget(view)
    blocker.setGeometry(view.rect())
    blocker.show()
    view.grab()
    assert not view._sketch_dimension_rects
    blocker.hide()
    view.pan_x = 10000
    view.grab()
    assert not view._sketch_dimension_rects
    view.pan_x = 0
    view.grab()
    assert view._sketch_dimension_rects
    view.set_mesh(None)
    view.grab()
    assert not view._sketch_dimension_rects


def test_bad_dimensions_rejected(qtbot):
    view = view_with_overlay(qtbot)
    path, vertex = view._sketch_path, view._sketch_vertex
    for dimensions in ((0, 0, 0, 20), (150, 20, 50, 0), (150, 20, 50, float('nan'))):
        with pytest.raises(ValueError):
            view.set_sketch_overlay(path, vertex, dimensions=dimensions)


@pytest.mark.parametrize('mode', ['independent', 'snapshot'])
def test_label_focuses_exact_input_only_for_current_draft(qtbot, monkeypatch, mode):
    if mode == 'independent':
        dialog = ready_dialog(qtbot, monkeypatch)
    else:
        _, dialog = ready_editor(qtbot, monkeypatch)
        monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.resize(1500, 1000)
    qtbot.wait(50)
    dialog._open_inline_sketch('front')
    editor, view = dialog._inline_sketch, dialog._cad._view
    editor.fields['R'].setText('20')
    editor.fields['Z'].setText(str(float(editor.fields['Z'].text()) + 50))
    view.grab()
    assert view._sketch_dimensions is not None and view._sketch_dimension_rects
    initial = tuple(field.text() for field in editor.fields.values())
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=view._sketch_dimension_rects['R'].center().toPoint())
    assert editor.fields['R'].hasFocus() and editor.fields['R'].selectedText() == '20'
    assert tuple(field.text() for field in editor.fields.values()) == initial
    editor.fields['R'].setText('25')
    assert view._sketch_dimensions[3] == 25
    view.grab()
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=view._sketch_dimension_rects['X'].center().toPoint())
    assert editor.fields['X'].hasFocus()
    editor.fields['R'].setText('nan')
    assert view._sketch_dimensions is None and not view._sketch_dimension_rects
    qtbot.keyClick(editor.fields['X'], Qt.Key.Key_Escape)
    assert not editor.isVisible() and view._sketch_dimensions is None
    assert dialog.shutdown()
    dialog.close()


def test_repaint_resize_or_data_change_between_press_and_release_cannot_target_old_label(qtbot):
    view = view_with_overlay(qtbot)
    requested = []
    view.sketch_dimension_requested.connect(requested.append)
    pos = view._sketch_dimension_rects['R'].center().toPoint()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=pos)
    view.pan_x += 20
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=pos)
    assert not requested
    view.grab()
    pos = view._sketch_dimension_rects['R'].center().toPoint()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=pos)
    view.set_sketch_overlay()
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=pos)
    assert not requested


def test_snapshot_second_edit_does_not_overwrite_pending_input(qtbot, monkeypatch):
    _, dialog = ready_editor(qtbot, monkeypatch)
    dialog._open_inline_sketch('front')
    editor = dialog._inline_sketch
    editor.fields['R'].setText('20')
    editor.fields['Z'].setText(str(float(editor.fields['Z'].text()) + 50))
    values = tuple(field.text() for field in editor.fields.values())
    dialog._open_inline_sketch('rear')
    assert dialog._inline_session[0] == 'front'
    assert tuple(field.text() for field in editor.fields.values()) == values
    assert 'Сначала' in editor.status.text()
    dialog._cad_context_menu('tube_rear', editor.mapToGlobal(editor.rect().center()))
    assert dialog._inline_session[0] == 'front'
    assert tuple(field.text() for field in editor.fields.values()) == values
    assert dialog.shutdown()
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()


@pytest.mark.parametrize('mode', ['independent', 'snapshot'])
def test_dimension_action_rechecks_unsignalled_stale_data(qtbot, monkeypatch, mode):
    if mode == 'independent':
        dialog = ready_dialog(qtbot, monkeypatch)
        def change():
            dialog._accepted_form = None
    else:
        controller, dialog = ready_editor(qtbot, monkeypatch)
        monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
        def change():
            controller.project.front.hardpoints['lbj'].x += 1
    dialog.resize(1500, 1000)
    qtbot.wait(50)
    dialog._open_inline_sketch('front')
    editor, view = dialog._inline_sketch, dialog._cad._view
    editor.fields['R'].setText('20')
    editor.fields['Z'].setText(str(float(editor.fields['Z'].text()) + 50))
    view.grab()
    pos = view._sketch_dimension_rects['R'].center().toPoint()
    change()
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=pos)
    assert dialog._inline_session is None and not editor.isVisible()
    assert view._sketch_dimensions is None
    assert dialog.shutdown()
    dialog.close()


def test_replacing_mesh_clears_draft_but_highlighting_same_mesh_preserves_it(qtbot):
    view = view_with_overlay(qtbot)
    mesh = view.mesh
    view.set_mesh(mesh)
    assert view._sketch_path and view._sketch_dimensions is not None
    replacement = CadMesh(mesh.triangles, mesh.face_count)
    view.set_mesh(replacement)
    assert not view._sketch_path and view._sketch_vertex is None and view._sketch_dimensions is None
    view.grab()
    assert not view._sketch_dimension_rects


@pytest.mark.parametrize('mode', ['independent', 'snapshot'])
def test_existing_bend_shows_parameters_when_reopened(qtbot, monkeypatch, mode):
    if mode == 'independent':
        dialog = ready_dialog(qtbot, monkeypatch)
    else:
        _, dialog = ready_editor(qtbot, monkeypatch)
        monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.resize(1500, 1000)
    qtbot.wait(50)
    dialog._open_inline_sketch('front')
    editor, view = dialog._inline_sketch, dialog._cad._view
    editor.fields['R'].setText('20')
    editor.fields['Z'].setText(str(float(editor.fields['Z'].text()) + 50))
    values = editor.values()
    qtbot.keyClick(editor.fields['R'], Qt.Key.Key_Return)
    assert dialog._inline_session is None
    qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    dialog._open_inline_sketch('front')
    view.grab()
    assert editor.values() == values and view._sketch_dimensions == values
    assert set(view._sketch_dimension_rects) == {'X', 'Y', 'Z', 'R'}
    qtbot.keyClick(editor.fields['X'], Qt.Key.Key_Escape)
    assert dialog.shutdown()
    dialog.close()
