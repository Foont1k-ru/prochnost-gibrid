"""3D-предпросмотр скелета не двигает точки и не подменяет проект."""
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from suspensionlab.core.scene3d import Scene3D, Segment3D
from suspensionlab.model.templates import load_template
from suspensionlab.ui.canvas.fixed_arm_scene import FixedArmScene
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog


def dialog_for_test(qtbot, monkeypatch):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.show()
    dialog._capture_snapshot()
    assert dialog.preview is not None and dialog._scene.frame is not None
    return controller, dialog


def test_click_anchor_and_vertex_are_selection_only(qtbot, monkeypatch):
    controller, dialog = dialog_for_test(qtbot, monkeypatch)
    scene = dialog._scene
    project_before = controller.project.to_dict()
    snapshot_before = dialog.snapshot
    anchor = scene.frame.point('lbj')
    assert anchor is not None
    pos = scene._screen_point(anchor).toPoint()
    assert scene._point_hits(QPointF(pos)) == ('lbj',)
    qtbot.mouseClick(scene, Qt.MouseButton.LeftButton, pos=pos)
    assert dialog._point_selection.currentData() == 'lbj' and scene.selected_point == 'lbj'
    assert 'Зафиксирована' in dialog._selection_status.text()
    a, b = dialog.preview.anchors[0], dialog.preview.anchors[2]
    vertex = [(a[i] + b[i]) / 2 for i in range(3)]
    vertex[2] += 70
    for field, value in zip(dialog._bend_editor.fields['front'], [*vertex, 20], strict=True):
        field.setText(str(value))
    dialog._bend_editor.checks['front'].setChecked(True)
    assert scene.frame.point('bend_front') == tuple(vertex)
    expected_segments = [(a, b) for path in dialog.preview.centerlines
                         for a, b in zip(path, path[1:], strict=False)]
    assert [(segment.start, segment.end) for segment in scene.frame.segments] == expected_segments
    assert tuple(vertex) not in dialog.preview.centerlines[0]  # the intersection is not the arc itself
    vpos = scene._screen_point(tuple(vertex)).toPoint()
    assert scene._point_hits(QPointF(vpos)) == ('bend_front',)
    qtbot.mouseClick(scene, Qt.MouseButton.LeftButton, pos=vpos)
    assert dialog._point_selection.currentData() == 'bend_front'
    assert 'не точка на дуге' in dialog._selection_status.text()
    assert controller.project.to_dict() == project_before and dialog.snapshot == snapshot_before
    assert dialog.preview.anchors == (scene.frame.point('lca_f_in'), scene.frame.point('lca_r_in'),
                                       scene.frame.point('lbj'))
    dialog.close()


def test_rotation_is_not_pick_and_does_not_modify_skeleton(qtbot, monkeypatch):
    controller, dialog = dialog_for_test(qtbot, monkeypatch)
    scene = dialog._scene
    old = (dialog._state(), dialog.preview, controller.project.to_dict())
    start = scene._screen_point(scene.frame.point('lbj'))
    qtbot.mousePress(scene, Qt.MouseButton.LeftButton, pos=start.toPoint())
    target = start + QPointF(40, 30)
    event = QMouseEvent(QEvent.Type.MouseMove, target, target, Qt.MouseButton.NoButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(scene, event)
    qtbot.mouseRelease(scene, Qt.MouseButton.LeftButton, pos=target.toPoint())
    assert scene.yaw != -0.65 and scene.elevation != 0.35
    assert dialog._point_selection.currentData() is None
    wheel = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, 0), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.ScrollUpdate, False)
    QApplication.sendEvent(scene, wheel)
    assert scene.zoom > 1
    assert (dialog._state(), dialog.preview, controller.project.to_dict()) == old
    assert not scene.grab().isNull()
    dialog._reset_camera.click()
    assert scene.yaw == -0.65 and scene.elevation == 0.35
    assert (dialog._state(), dialog.preview, controller.project.to_dict()) == old
    dialog.close()


def test_ambiguous_projection_never_selects_arbitrary_point(qtbot):
    scene = FixedArmScene()
    qtbot.addWidget(scene)
    scene.resize(400, 300)
    scene.show()
    scene.set_standard_view('top')
    # Vertically distinct points overlap in the top view.
    a, b = (0., 0., 0.), (0., 0., 20.)
    scene.set_scene(Scene3D(0, (Segment3D(a, b, 'arm'),), (('lca_f_in', a), ('lca_r_in', b))))
    picks, ambiguous = [], []
    scene.pointPicked.connect(picks.append)
    scene.ambiguousPick.connect(lambda: ambiguous.append(True))
    position = scene._screen_point(a)
    assert set(scene._point_hits(position)) == {'lca_f_in', 'lca_r_in'}
    qtbot.mouseClick(scene, Qt.MouseButton.LeftButton, pos=position.toPoint())
    assert not picks and ambiguous == [True]


def test_scene_disappears_when_input_invalid_or_project_stale(qtbot, monkeypatch):
    controller, dialog = dialog_for_test(qtbot, monkeypatch)
    dialog._bend_editor.checks['front'].setChecked(True)
    assert dialog.preview is None and dialog._scene.frame is None
    dialog._bend_editor.checks['front'].setChecked(False)
    assert dialog.preview is not None and dialog._scene.frame is not None
    point = controller.project.front.hardpoints['lbj']
    controller.move_point(point, (point.x + 1, point.y, point.z))
    assert dialog.snapshot is None and dialog._scene.frame is None and dialog.preview is None
    assert not dialog._point_selection.isEnabled() and not dialog._save.isEnabled()
    dialog.close()


def test_3d_selection_and_camera_do_not_change_saved_skeleton(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    controller, dialog = dialog_for_test(qtbot, monkeypatch)
    before = controller.project.to_dict()
    first, second = tmp_path / 'first.slarm', tmp_path / 'second.slarm'
    paths = iter([str(first), str(second)])
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (next(paths), ''))
    dialog._save_file()
    assert first.exists()
    dialog._point_selection.setCurrentIndex(dialog._point_selection.findData('lbj'))
    dialog._scene.set_standard_view('top')
    dialog._scene.zoom = 2
    dialog._scene.pan_x, dialog._scene.pan_y = 10, -5
    dialog._save_file()
    assert second.exists() and first.read_bytes() == second.read_bytes()
    assert controller.project.to_dict() == before
    dialog.close()
