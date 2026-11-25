"""Рабочее пространство и временный эскиз поверх актуальной CAD-сетки."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
from test_fixed_arm_tube_joint_ui import make_editor


def ready_editor(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_editor(qtbot, monkeypatch)
    dialog._advanced_toggle.setChecked(False)
    dialog._cad._quality.setCurrentIndex(1)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    return controller, dialog


def test_workspace_and_right_click_inline_apply(qtbot, monkeypatch):
    controller, dialog = ready_editor(qtbot, monkeypatch)
    view = dialog._cad._view
    assert not dialog._cad_tools.isVisible()
    dialog._settings_toggle.setChecked(False)
    assert not dialog._settings_toggle.isChecked()
    dialog._settings_toggle.setChecked(True)
    dialog._advanced_toggle.setChecked(True)
    assert dialog._cad_tools.isVisible()
    dialog._advanced_toggle.setChecked(False)
    mesh = view.mesh
    triangle = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('tube_front'))[0])
    def choose():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(action for action in menu.actions() if action.text() == 'Редактировать эскиз на модели')
        qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    QTimer.singleShot(50, choose)
    with monkeypatch.context() as patch:
        patch.setattr(view, '_pick_index', lambda *args: triangle)
        qtbot.mouseClick(view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    editor = dialog._inline_sketch
    assert editor.isVisible() and view._sketch_path and not dialog._bend_editor.values()
    assert editor.parent() is view
    assert editor.x() + editor.width() <= view.width() and editor.y() + editor.height() <= view.height()
    editor.fields['R'].setText('20')
    assert not view._sketch_path  # midpoint on the straight line is not a valid bend
    editor.fields['Z'].setText(str(float(editor.fields['Z'].text()) + 50))
    assert view._sketch_path and view._sketch_vertex is not None
    assert not dialog._bend_editor.values()  # draft does not change the document
    view.grab()  # overlay painting
    old_anchors = dialog.preview.anchors
    qtbot.keyClick(editor.fields['R'], Qt.Key.Key_Return)
    assert not editor.isVisible() and not view._sketch_path
    assert dialog._bend_editor.values()['front']['radius_mm'] == 20
    assert dialog.preview.anchors == old_anchors
    assert view.mesh is None  # stale CAD hidden until rebuild
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    assert dialog.snapshot.matches(controller.project)
    assert dialog.shutdown()
    dialog.close()


def test_inline_cancel_invalid_and_stale(qtbot, monkeypatch):
    controller, dialog = ready_editor(qtbot, monkeypatch)
    dialog._open_inline_sketch('rear')
    editor = dialog._inline_sketch
    editor.fields['R'].setText('nan')
    qtbot.keyClick(editor.fields['R'], Qt.Key.Key_Return)
    assert editor.isVisible() and not dialog._bend_editor.values()
    qtbot.keyClick(editor.fields['R'], Qt.Key.Key_Escape)
    assert not editor.isVisible() and not dialog._cad._view._sketch_path
    dialog._open_inline_sketch('front')
    controller.project.front.hardpoints['lbj'].x += 1
    editor.fields['R'].setText('20')
    assert not editor.isVisible() and not dialog._bend_editor.values()
    assert not dialog._cad._view._sketch_path
    dialog._refresh()
    assert dialog.snapshot is None and dialog._cad._view.mesh is None
    assert dialog.shutdown()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.close()


def test_right_click_empty_does_not_reuse_selection(qtbot, monkeypatch):
    _, dialog = ready_editor(qtbot, monkeypatch)
    view = dialog._cad._view
    requested = []
    view.context_requested.connect(requested.append)
    with monkeypatch.context() as patch:
        patch.setattr(view, '_pick_index', lambda *args: None)
        qtbot.mouseClick(view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert not requested
    assert dialog.shutdown()
    dialog.close()


def test_right_click_picks_visible_surface(qtbot, monkeypatch):
    from suspensionlab.core.cad_raster import screen_projection

    _, dialog = ready_editor(qtbot, monkeypatch)
    cad, view = dialog._cad, dialog._cad._view
    cad.partContextRequested.disconnect(dialog._cad_context_menu)
    requested = []
    cad.partContextRequested.connect(lambda part, position: requested.append(part))
    ratio = view.devicePixelRatioF()
    width, height = round(view.width() * ratio), round(view.height() * ratio)
    projected, _ = screen_projection(view.mesh.triangles, view._center, view._radius, view.yaw, view.elevation,
                                      view.zoom, width, height, 24 * ratio, offset=view._pixel_offset(width, height))
    pos = None
    expected = None
    for point in projected.mean(axis=1)[::20]:
        x, y = (int(point[0]), int(point[1]))
        if 0 <= x < width and 0 <= y < height:
            index = view._pick_index(x, y, width, height, ratio)
            if index is not None:
                pos = QPoint(round(x * view.width() / width), round(y * view.height() / height))
                expected = view.mesh.part_names[int(view.mesh.triangle_parts[index])]
                break
    assert pos is not None
    qtbot.mouseClick(view, Qt.MouseButton.RightButton, pos=pos)
    assert requested == [expected]
    assert dialog.shutdown()
    dialog.close()
