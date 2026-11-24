"""Непосредственное редактирование с фиксированными опорами и явным радиусом."""
from copy import deepcopy
from math import cos, dist, sin

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def setup_dialog(qtbot, monkeypatch):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.show()
    dialog._capture_snapshot()
    assert dialog.preview is not None
    return controller, dialog


def move(canvas, position):
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(position), QPointF(position), Qt.MouseButton.NoButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(canvas, event)


def create_draft(qtbot, dialog, leg='front'):
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    a, b = dialog.preview.centerlines[0 if leg == 'front' else 1]
    pos = canvas._screen_point(tuple(a[i] * .6 + b[i] * .4 for i in range(3))).toPoint()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pos)
    assert dialog._draft is not None and dialog._draft[0] == leg
    return canvas


def test_click_tube_drag_create_bend_and_show_actual_lengths(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    project = deepcopy(controller.project.to_dict())
    anchors = dialog.preview.anchors
    canvas = create_draft(qtbot, dialog)
    assert not dialog._save.isEnabled() and dialog._cad._document is None
    assert not dialog._bend_editor.isVisible()
    pos = canvas._screen_point(dialog._draft[1]).toPoint()
    target = pos + QPoint(70, 0)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (30., True))
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    move(canvas, target)
    assert 'Кандидат: X=' in dialog._selection_status.text()
    assert 'До виртуальной вершины' in dialog._lengths.text()
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert dialog._draft is None and dialog.preview is not None and dialog._save.isEnabled()
    assert dialog.preview.anchors == anchors and controller.project.to_dict() == project
    assert list(dialog._bend_editor.values()) == ['front']
    assert dialog._bend_editor.values()['front']['radius_mm'] == 30
    assert 'дуга' in dialog._lengths.text() and 'Задняя: прямая' in dialog._lengths.text()
    assert dialog._cad._document['parts'][0]['geometry']['kind'] == 'prototype_arm_bent_tube'
    dialog.close()


def test_draft_cancel_invalid_radius_and_project_change(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    canvas = create_draft(qtbot, dialog, 'rear')
    original = deepcopy(controller.project.to_dict()), dialog.preview
    pos = canvas._screen_point(dialog._draft[1]).toPoint()
    target = pos + QPoint(-60, 0)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (2., True))
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    move(canvas, target)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert dialog._draft is not None and not dialog._bend_editor.values()
    assert (controller.project.to_dict(), dialog.preview) == original
    assert 'не принято' in dialog._selection_status.text() and not dialog._save.isEnabled()
    dialog._remove_bend.click()
    assert dialog._draft is None and dialog._save.isEnabled() and not dialog._bend_editor.values()
    canvas = create_draft(qtbot, dialog)
    point = controller.project.front.hardpoints['lbj']
    controller.move_point(point, (point.x + 1, point.y, point.z))
    assert dialog.snapshot is None and dialog.preview is None and dialog._draft is None
    assert canvas.preview is None and dialog._cad._document is None
    dialog.close()


def test_3d_drag_moves_vertex_in_screen_plane_and_keeps_anchors(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    canvas = create_draft(qtbot, dialog)
    pos = canvas._screen_point(dialog._draft[1]).toPoint()
    target = pos + QPoint(70, 0)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (30., True))
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    move(canvas, target)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    dialog._tabs.setCurrentIndex(0)
    scene = dialog._scene
    before = tuple(dialog._bend_editor.values()['front']['vertex_mm'])
    anchor = dialog.preview.anchors
    project = deepcopy(controller.project.to_dict())
    pos = scene._screen_point(before).toPoint()
    assert scene._point_hits(QPointF(pos)) == ('bend_front',)
    target = pos + QPoint(15, -10)
    yaw, elevation = scene.yaw, scene.elevation
    qtbot.mousePress(scene, Qt.MouseButton.LeftButton, pos=pos)
    move(scene, target)
    assert 'Кандидат:' in dialog._selection_status.text()
    qtbot.mouseRelease(scene, Qt.MouseButton.LeftButton, pos=target)
    after = tuple(dialog._bend_editor.values()['front']['vertex_mm'])
    assert dist(before, after) > 1 and (scene.yaw, scene.elevation) == (yaw, elevation)
    normal = (sin(yaw) * cos(elevation), -cos(yaw) * cos(elevation), sin(elevation))
    assert sum((after[i] - before[i]) * normal[i] for i in range(3)) == pytest.approx(0, abs=1e-9)
    assert dialog.preview.anchors == anchor and controller.project.to_dict() == project
    dialog.close()


def test_radius_change_invalid_or_cancel_preserves_shape(qtbot, monkeypatch):
    _, dialog = setup_dialog(qtbot, monkeypatch)
    canvas = create_draft(qtbot, dialog)
    pos = canvas._screen_point(dialog._draft[1]).toPoint()
    target = pos + QPoint(70, 0)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (30., True))
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    move(canvas, target)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    before = dialog._state(), dialog.preview
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (0., False))
    dialog._edit_radius.click()
    assert (dialog._state(), dialog.preview) == before
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (2., True))
    dialog._edit_radius.click()
    assert (dialog._state(), dialog.preview) == before and 'не принят' in dialog._selection_status.text()
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (25., True))
    dialog._edit_radius.click()
    assert dialog._bend_editor.values()['front']['radius_mm'] == 25
    dialog._remove_bend.click()
    assert not dialog._bend_editor.values() and dialog.preview is not None
    dialog.close()


def test_create_by_clicking_3d_tube_and_dragging_in_3d(qtbot, monkeypatch):
    _, dialog = setup_dialog(qtbot, monkeypatch)
    scene = dialog._scene
    a, b = dialog.preview.centerlines[0]
    point = tuple(a[i] * .6 + b[i] * .4 for i in range(3))
    pos = scene._screen_point(point).toPoint()
    qtbot.mouseClick(scene, Qt.MouseButton.LeftButton, pos=pos)
    assert dialog._draft is not None and dialog._draft[0] == 'front'
    pos = scene._screen_point(dialog._draft[1]).toPoint()
    target = pos + QPoint(65, -30)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (30., True))
    qtbot.mousePress(scene, Qt.MouseButton.LeftButton, pos=pos)
    move(scene, target)
    qtbot.mouseRelease(scene, Qt.MouseButton.LeftButton, pos=target)
    assert dialog._draft is None and 'front' in dialog._bend_editor.values()
    assert dialog.preview is not None and dialog._save.isEnabled()
    dialog.close()


def test_exact_coordinates_do_not_silently_move_anchors(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog, QLineEdit

    controller, dialog = setup_dialog(qtbot, monkeypatch)
    canvas = create_draft(qtbot, dialog)
    pos = canvas._screen_point(dialog._draft[1]).toPoint()
    target = pos + QPoint(70, 0)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (30., True))
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    move(canvas, target)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    original = dialog._bend_editor.values()['front']['vertex_mm']
    anchors = dialog.preview.anchors
    project = deepcopy(controller.project.to_dict())

    def accept_coordinates(editor):
        field = editor.findChild(QLineEdit, 'coordinate_Z')
        field.setText('222,123456789')
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, 'exec', accept_coordinates)
    dialog._edit_coordinates.click()
    vertex = dialog._bend_editor.values()['front']['vertex_mm']
    assert vertex[:2] == original[:2] and vertex[2] == pytest.approx(222.123456789)
    assert dialog.preview.anchors == anchors and controller.project.to_dict() == project
    dialog.close()


def test_geometry_during_radius_dialog_change_is_not_committed(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    canvas = create_draft(qtbot, dialog)
    pos = canvas._screen_point(dialog._draft[1]).toPoint()
    target = pos + QPoint(70, 0)

    def change_project(*args):
        point = controller.project.front.hardpoints['lbj']
        controller.move_point(point, (point.x + 1, point.y, point.z))
        return 30., True

    monkeypatch.setattr(QInputDialog, 'getDouble', change_project)
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    move(canvas, target)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert dialog.snapshot is None and dialog.preview is None and dialog._draft is None
    assert not dialog._bend_editor.values()
    dialog.close()


def test_two_bends_remain_independent_and_delete_one(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    project, anchors = deepcopy(controller.project.to_dict()), dialog.preview.anchors
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (30., True))
    for leg, dx in (('front', 70), ('rear', -70)):
        canvas = create_draft(qtbot, dialog, leg)
        pos = canvas._screen_point(dialog._draft[1]).toPoint()
        target = pos + QPoint(dx, 0)
        qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
        move(canvas, target)
        qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert set(dialog._bend_editor.values()) == {'front', 'rear'}
    rear = deepcopy(dialog._bend_editor.values()['rear'])
    dialog._point_selection.setCurrentIndex(dialog._point_selection.findData('bend_front'))
    dialog._remove_bend.click()
    assert dialog._bend_editor.values() == {'rear': rear}
    assert dialog.preview.anchors == anchors and controller.project.to_dict() == project
    dialog.close()


def test_3d_escape_and_switch_view_cancel_drag(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    canvas = create_draft(qtbot, dialog)
    pos = canvas._screen_point(dialog._draft[1]).toPoint()
    target = pos + QPoint(70, 0)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (30., True))
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    move(canvas, target)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    dialog._tabs.setCurrentIndex(0)
    scene = dialog._scene
    old = dialog._state(), dialog.preview, deepcopy(controller.project.to_dict())
    pos = scene._screen_point(tuple(dialog._bend_editor.values()['front']['vertex_mm'])).toPoint()
    target = pos + QPoint(30, 20)
    qtbot.mousePress(scene, Qt.MouseButton.LeftButton, pos=pos)
    move(scene, target)
    qtbot.keyClick(scene, Qt.Key.Key_Escape)
    qtbot.mouseRelease(scene, Qt.MouseButton.LeftButton, pos=target)
    assert (dialog._state(), dialog.preview, controller.project.to_dict()) == old
    qtbot.mousePress(scene, Qt.MouseButton.LeftButton, pos=pos)
    move(scene, target)
    dialog._tabs.setCurrentIndex(1)
    qtbot.mouseRelease(scene, Qt.MouseButton.LeftButton, pos=target)
    assert (dialog._state(), dialog.preview, controller.project.to_dict()) == old
    dialog.close()


def test_overlapping_tubes_do_not_guess_which_bend_to_create(qtbot):
    from suspensionlab.model.fixed_arm_skeleton import SkeletonPreview
    from suspensionlab.ui.canvas.fixed_arm_projection import SkeletonProjection

    canvas = SkeletonProjection((0, 1))
    qtbot.addWidget(canvas)
    canvas.resize(400, 300)
    canvas.show()
    a, b, c = (0., 0., 0.), (0., 0., 40.), (100., 100., 10.)
    canvas.set_preview(SkeletonPreview(((a, c), (b, c)), (a, b, c)),
                       (('lca_f_in', a), ('lca_r_in', b), ('lbj', c)))
    ambiguous, picks = [], []
    canvas.ambiguousPick.connect(lambda: ambiguous.append(True))
    canvas.segmentPicked.connect(lambda *args: picks.append(args))
    point = canvas._screen_point((50., 50., 0.)).toPoint()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert ambiguous == [True] and not picks


@pytest.mark.parametrize('index', [0, 1])
def test_switch_view_cancels_pending_line_click(qtbot, monkeypatch, index):
    _, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(index)
    canvas = dialog._scene if index == 0 else dialog._projections[0]
    a, b = dialog.preview.centerlines[0]
    point = tuple(a[i] * .6 + b[i] * .4 for i in range(3))
    pos = canvas._screen_point(point).toPoint()
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    dialog._tabs.setCurrentIndex(2)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=pos)
    assert dialog._draft is None and dialog.preview is not None
    dialog.close()
