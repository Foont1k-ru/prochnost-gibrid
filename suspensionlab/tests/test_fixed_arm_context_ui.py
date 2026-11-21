"""Контекстное управление выбранной трубой без потери сдвига камеры."""
import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox
from test_fixed_arm_tube_joint_ui import make_editor


def _select_part(cad, part):
    mesh = cad._view.mesh
    group = mesh.part_names.index(part)
    index = int(np.flatnonzero(mesh.triangle_parts == group)[0])
    cad._view.triangle_picked.emit(index)


def _start_cut(dialog, qtbot, monkeypatch, part='tube_front'):
    _select_part(dialog._cad, part)
    def choose():
        menu = QApplication.activePopupWidget()
        if isinstance(menu, QMenu):
            action = next((action for action in menu.actions() if action.text().startswith('Обрезать')), None)
            if action is not None:
                qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
            else:
                menu.close()
    QTimer.singleShot(50, choose)
    qtbot.mouseClick(dialog._cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert dialog._cad_cut_pick is not None and dialog._cad_cut_pick[0] == part


def test_mouse_menu_cutter_miter_and_undo(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    _start_cut(dialog, qtbot, monkeypatch)
    root = cad._parts_tree.topLevelItem(0)
    cad._parts_tree.setCurrentItem(root.child(1))  # Tree selection alone must not choose a cutter.
    assert dialog._cad_cut_pick is not None and dialog._tube_joint.currentData() is None
    _select_part(cad, 'tube_front')
    assert dialog._cad_cut_pick is not None and 'другую трубу' in dialog._cad_pick_status.text()
    _select_part(cad, 'tube_rear')
    assert dialog._cad_cut_pick is None and dialog._tube_joint.currentData() == 'miter'
    assert cad._view.mesh is None
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    assert 'обе трубы' in cad._status.text().lower()
    dialog._undo_trim()
    assert dialog._tube_joint.currentData() is None and cad._view.mesh is None
    assert dialog.shutdown()
    dialog.close()


def test_right_drag_remains_pan_and_escape_cancels_pick(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    _select_part(cad, 'tube_front')
    requested = []
    cad._view.context_requested.connect(requested.append)
    view = cad._view
    start, end = QPoint(100, 100), QPoint(145, 130)
    qtbot.mousePress(view, Qt.MouseButton.RightButton, pos=start)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(end), Qt.MouseButton.NoButton,
                        Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view, event)
    qtbot.mouseRelease(view, Qt.MouseButton.RightButton, pos=end)
    assert not requested and (view.pan_x != 0 or view.pan_y != 0)
    _start_cut(dialog, qtbot, monkeypatch)
    qtbot.keyClick(view, Qt.Key.Key_Escape)
    assert dialog._cad_cut_pick is None and not dialog._cad_pick_cancel.isVisible()
    assert dialog.shutdown()
    dialog.close()


def test_cut_selection_cancelled_on_change_and_no_silent_replacement(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    _start_cut(dialog, qtbot, monkeypatch)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    _select_part(cad, 'tube_rear')
    assert dialog._cad_cut_pick is not None and dialog._tube_joint.currentData() is None
    controller.project.front.hardpoints['lbj'].x += 1
    _select_part(cad, 'tube_rear')
    assert dialog._cad_cut_pick is None and dialog._tube_joint.currentData() is None
    assert dialog.shutdown()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.close()


def test_mouse_cut_own_housing_preserves_other_operations(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from test_fixed_arm_housings import housings

    _, dialog = make_editor(qtbot, monkeypatch)
    dialog._housings = housings()
    dialog._refresh()
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    _start_cut(dialog, qtbot, monkeypatch)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (1., True))
    _select_part(cad, 'housing_rear')
    assert dialog._cad_cut_pick is not None and 'Другие резы' in dialog._cad_pick_status.text()
    _select_part(cad, 'housing_front')
    assert dialog._cad_cut_pick is None
    assert dialog._notch_values() == {'front': 1.}
    assert dialog._tube_joint_values() is None
    dialog._undo_trim()
    assert dialog._notch_values() is None
    assert dialog.shutdown()
    dialog.close()


def test_actual_left_click_selects_second_tube(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.core.cad_raster import pick_triangle, screen_projection

    _, dialog = make_editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    _start_cut(dialog, qtbot, monkeypatch)
    view = cad._view
    ratio = view.devicePixelRatioF()
    width, height = round(view.width() * ratio), round(view.height() * ratio)
    offset = view._pixel_offset(width, height)
    projected, _ = screen_projection(view._triangles, view._center, view._radius, view.yaw, view.elevation,
                                     view.zoom, width, height, 24 * ratio, offset=offset)
    rear = cad._view.mesh.part_names.index('tube_rear')
    point = None
    for i in np.flatnonzero(cad._view.mesh.triangle_parts == rear):
        center = np.mean(projected[i], axis=0)
        x, y = int(center[0]), int(center[1])
        if not (0 <= x < width and 0 <= y < height):
            continue
        hit = pick_triangle(view._triangles, view._center, view._radius, view.yaw, view.elevation,
                            view.zoom, width, height, x, y, margin=24 * ratio,
                            highlight=view._highlight, through=view._through, offset=offset)
        if hit is not None and cad._view.mesh.triangle_parts[hit] == rear:
            point = QPoint(round(x / ratio), round(y / ratio))
            break
    assert point is not None
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=point)
    assert dialog._cad_cut_pick is None and dialog._tube_joint.currentData() == 'miter'
    assert dialog.shutdown()
    dialog.close()


def test_stale_during_joint_confirmation_cancels_operation(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    _start_cut(dialog, qtbot, monkeypatch)
    def stale(*args):
        controller.project.front.hardpoints['lbj'].x += 1
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', stale)
    _select_part(cad, 'tube_rear')
    assert dialog._cad_cut_pick is None and dialog._tube_joint.currentData() is None
    assert cad._view.mesh is None and dialog.snapshot is None
    assert dialog.shutdown()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.close()
