"""Редактирование вершины в проекциях: только две оси и только допустимый кандидат."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from suspensionlab.model.fixed_arm_skeleton import SkeletonPreview
from suspensionlab.model.fixed_arm_skeleton_io import read_skeleton
from suspensionlab.model.templates import load_template
from suspensionlab.ui.canvas.fixed_arm_projection import SkeletonProjection
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def setup_dialog(qtbot, monkeypatch, *, vertex_z=None):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.show()
    dialog._capture_snapshot()
    a, b = dialog.preview.anchors[0], dialog.preview.anchors[2]
    vertex = [(a[0] + b[0]) / 2 + 70, (a[1] + b[1]) / 2,
              (a[2] + b[2]) / 2 + 70.12345678901234 if vertex_z is None else vertex_z]
    for field, value in zip(dialog._bend_editor.fields['front'], [*vertex, 20], strict=True):
        field.setText(str(value))
    dialog._bend_editor.checks['front'].setChecked(True)
    assert dialog.preview is not None
    return controller, dialog


def move_with_button(canvas, position):
    event = QMouseEvent(QEvent.Type.MouseMove, position, position, Qt.MouseButton.NoButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(canvas, event)


@pytest.mark.parametrize('index,axes', [(0, (0, 1)), (1, (0, 2)), (2, (1, 2))])
def test_drag_moves_only_visible_axes_and_saves(qtbot, monkeypatch, tmp_path, index, axes):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(index + 1)
    canvas = dialog._projections[index]
    old_project, old_snapshot = deepcopy(controller.project.to_dict()), dialog.snapshot
    old_preview = dialog.preview
    old_bend = dialog._bend_editor.values()['front']['vertex_mm'][:]
    hidden_axis = ({0, 1, 2} - set(axes)).pop()
    hidden_text = dialog._bend_editor.fields['front'][hidden_axis].text()
    start = canvas._screen_point(tuple(old_bend)).toPoint()
    assert canvas._point_hits(QPointF(start)) == ('bend_front',)
    _, _, scale = canvas._transform()
    end = start + type(start)(18, -12)
    size_before = (canvas.width(), canvas.height())
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QApplication.processEvents()  # selection text must not resize the view mid-gesture
    assert (canvas.width(), canvas.height()) == size_before
    move_with_button(canvas, QPointF(end))
    assert dialog.preview == old_preview and dialog._bend_editor.values()['front']['vertex_mm'] == old_bend
    assert canvas._drag is not None and canvas._drag.moved and not canvas.grab().isNull()
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    new = dialog._bend_editor.values()['front']['vertex_mm']
    assert new[axes[0]] == pytest.approx(old_bend[axes[0]] + 18 / scale)
    assert new[axes[1]] == pytest.approx(old_bend[axes[1]] + 12 / scale)
    assert new[hidden_axis] == old_bend[hidden_axis]
    assert dialog._bend_editor.fields['front'][hidden_axis].text() == hidden_text
    assert dialog.preview != old_preview and dialog.preview.anchors == old_preview.anchors
    assert dialog.snapshot == old_snapshot and controller.project.to_dict() == old_project
    assert dialog._scene.frame.point('bend_front') == tuple(new)
    assert dialog._point_selection.currentData() == 'bend_front'
    from PySide6.QtWidgets import QFileDialog

    path = tmp_path / 'edited.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    assert path.exists()
    loaded = read_skeleton(path, controller.project)
    assert loaded.bends['front']['vertex_mm'] == new
    assert loaded.snapshot == old_snapshot
    dialog.close()


@pytest.mark.parametrize('index,axes', [(0, (0, 1)), (1, (0, 2)), (2, (1, 2))])
def test_inline_projection_offsets_preserve_other_coordinates(qtbot, monkeypatch, index, axes):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(index + 1)
    canvas = dialog._projections[index]
    dialog._point_picked('bend_front')
    assert canvas._dimensions.isVisible()
    before = dialog._bend_editor.values()['front']['vertex_mm'][:]
    assert not canvas._dimensions.geometry().contains(canvas._screen_point(tuple(before)).toPoint())
    original_project = deepcopy(controller.project.to_dict())
    anchor = dialog.preview.anchors[0]
    new_offset = before[axes[0]] - anchor[axes[0]] + 7.25
    canvas._dimension_fields[0].setText(str(new_offset))
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    after = dialog._bend_editor.values()['front']['vertex_mm']
    hidden_axis = ({0, 1, 2} - set(axes)).pop()
    assert after[axes[0]] == pytest.approx(anchor[axes[0]] + new_offset)
    assert after[axes[1]] == before[axes[1]]
    assert after[hidden_axis] == before[hidden_axis]
    assert controller.project.to_dict() == original_project
    assert 'В проекции' in canvas._dimension_distances.text()
    dialog.close()


def test_inline_offsets_can_finish_a_draft(qtbot, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._capture_snapshot()
    dialog._tabs.setCurrentIndex(1)
    anchor, ball = dialog.preview.anchors[0], dialog.preview.anchors[2]
    midpoint = tuple((x + y) / 2 for x, y in zip(anchor, ball, strict=True))
    dialog._create_draft('front', midpoint)
    canvas = dialog._projections[0]
    assert canvas._dimensions.isVisible()
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (20., True))
    canvas._dimension_fields[0].setText(str(midpoint[0] - anchor[0] + 50.))
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    assert dialog._draft is None
    assert dialog._bend_editor.values()['front']['vertex_mm'][0] == pytest.approx(midpoint[0] + 50.)
    assert dialog._bend_editor.values()['front']['vertex_mm'][2] == midpoint[2]
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.close()


def test_inline_projection_rejects_invalid_numbers_and_stale_project(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    dialog._point_picked('bend_front')
    before = dialog._bend_editor.values()['front']['vertex_mm'][:]
    canvas._dimension_fields[0].setText('nan')
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    assert dialog._bend_editor.values()['front']['vertex_mm'] == before
    assert dialog.isVisible() and canvas._dimension_error.isVisible()
    canvas._dimension_fields[0].setText('90')
    controller.project.front.hardpoints['lbj'].x += 0.000001
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    assert dialog._bend_editor.values()['front']['vertex_mm'] == before
    assert dialog.snapshot is None and dialog.preview is None
    dialog.close()


def test_invalid_drag_does_not_replace_valid_preview(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch, vertex_z=140)
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    original = dialog._state(), dialog.preview, deepcopy(controller.project.to_dict())
    vertex = dialog._bend_editor.values()['front']['vertex_mm']
    start = canvas._screen_point(tuple(vertex)).toPoint()
    target = canvas._screen_point(dialog.preview.anchors[0]).toPoint()
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    move_with_button(canvas, QPointF(target))
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert (dialog._state(), dialog.preview, controller.project.to_dict()) == original
    assert 'не принято' in dialog._selection_status.text() and 'прежний скелет' in dialog._selection_status.text()
    assert dialog._save.isEnabled() and dialog._scene.frame is not None
    dialog.close()


def test_drag_anchor_and_cancel_leave_all_geometry_unchanged(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    original = dialog._state(), dialog.preview, deepcopy(controller.project.to_dict())
    anchor = canvas._screen_point(dialog.preview.anchors[0]).toPoint()
    assert canvas._point_hits(QPointF(anchor)) == ('lca_f_in',)
    target = anchor + type(anchor)(40, 30)
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=anchor)
    move_with_button(canvas, QPointF(target))
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert (dialog._state(), dialog.preview, controller.project.to_dict()) == original
    assert dialog._point_selection.currentData() == 'lca_f_in'
    vertex = tuple(dialog._bend_editor.values()['front']['vertex_mm'])
    start = canvas._screen_point(vertex).toPoint()
    end = start + type(start)(40, 30)
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    move_with_button(canvas, QPointF(end))
    qtbot.keyClick(canvas, Qt.Key.Key_Escape)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert (dialog._state(), dialog.preview, controller.project.to_dict()) == original
    assert canvas._drag is None
    dialog.close()


@pytest.mark.parametrize('signalled', [True, False])
def test_project_change_during_drag_is_not_applied(qtbot, monkeypatch, signalled):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    vertex = tuple(dialog._bend_editor.values()['front']['vertex_mm'])
    start = canvas._screen_point(vertex).toPoint()
    end = start + type(start)(18, 12)
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    move_with_button(canvas, QPointF(end))
    pt = controller.project.front.hardpoints['lbj']
    if signalled:
        controller.move_point(pt, (pt.x + 1, pt.y, pt.z))
    else:
        pt.x += 0.000001
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tuple(dialog._bend_editor.values()['front']['vertex_mm']) == vertex
    assert dialog.snapshot is None and dialog.preview is None and canvas.preview is None
    assert not dialog._save.isEnabled()
    dialog.close()


def test_overlapping_markers_are_not_dragged(qtbot):
    canvas = SkeletonProjection((0, 1))
    qtbot.addWidget(canvas)
    canvas.resize(400, 300)
    canvas.show()
    a, b = (0., 0., 0.), (100., 100., 0.)
    canvas.set_preview(SkeletonPreview(((a, b), (a, b)), (a, a, b)),
                       (('lca_f_in', a), ('bend_front', (0., 0., 100.))))
    ambiguous, started = [], []
    canvas.ambiguousPick.connect(lambda: ambiguous.append(True))
    canvas.dragStarted.connect(started.append)
    pos = canvas._screen_point(a).toPoint()
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=pos)
    assert ambiguous == [True] and not started and canvas._drag is None

def test_switch_projection_and_change_field_cancel_gesture(qtbot, monkeypatch):
    _controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    vertex = tuple(dialog._bend_editor.values()['front']['vertex_mm'])
    start = canvas._screen_point(vertex).toPoint()
    target = start + type(start)(20, 15)
    original = dialog._state(), dialog.preview
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    move_with_button(canvas, QPointF(target))
    dialog._tabs.setCurrentIndex(2)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert (dialog._state(), dialog.preview) == original and canvas._drag is None
    dialog._tabs.setCurrentIndex(1)
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    move_with_button(canvas, QPointF(target))
    dialog._bend_editor.fields['front'][3].setText('25')
    changed = dialog._state(), dialog.preview
    assert changed != original and dialog.preview is not None and canvas._drag is None
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert (dialog._state(), dialog.preview) == changed
    assert tuple(dialog._bend_editor.values()['front']['vertex_mm']) == vertex
    dialog.close()
