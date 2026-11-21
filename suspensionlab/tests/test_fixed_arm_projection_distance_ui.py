"""Проекционные расстояния двигают только вершину и только по выбранному лучу."""
from copy import deepcopy
from math import hypot

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox
from test_fixed_arm_projection_drag_ui import setup_dialog

from suspensionlab.model.fixed_arm_skeleton import SkeletonPreview
from suspensionlab.ui.canvas.fixed_arm_projection import SkeletonProjection


@pytest.mark.parametrize('index,axes', [(0, (0, 1)), (1, (0, 2)), (2, (1, 2))])
@pytest.mark.parametrize('reference_index', [0, 1])
def test_distance_keeps_ray_and_hidden_coordinate(qtbot, monkeypatch, index, axes, reference_index):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(index + 1)
    canvas = dialog._projections[index]
    dialog._point_picked('bend_front')
    before = dialog._bend_editor.values()['front']['vertex_mm'][:]
    project = deepcopy(controller.project.to_dict())
    anchors = dialog.preview.anchors
    ref = anchors[0 if reference_index == 0 else 2]
    old = hypot(*(before[axis] - ref[axis] for axis in axes))
    target = old * 1.04
    field = canvas._distance_fields[reference_index]
    field.setText(str(target))
    qtbot.keyClick(field, Qt.Key.Key_Return)
    after = dialog._bend_editor.values()['front']['vertex_mm']
    for axis in axes:
        assert after[axis] == pytest.approx(ref[axis] + 1.04 * (before[axis] - ref[axis]))
    hidden = ({0, 1, 2} - set(axes)).pop()
    assert after[hidden] == before[hidden]
    assert hypot(*(after[axis] - ref[axis] for axis in axes)) == pytest.approx(target)
    assert dialog.preview.anchors == anchors and controller.project.to_dict() == project
    assert dialog.isVisible()
    dialog.close()


def test_invalid_conflicting_and_unchanged_inputs(qtbot, monkeypatch):
    _, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    dialog._point_picked('bend_front')
    before = dialog._bend_editor.values()['front']['vertex_mm'][:]
    field = canvas._distance_fields[0]
    for text in ('nan', 'inf', '-1', '0', '1000001', 'abc'):
        field.setText(text)
        qtbot.keyClick(field, Qt.Key.Key_Return)
        assert dialog.isVisible() and canvas._dimension_error.isVisible()
        assert dialog._bend_editor.values()['front']['vertex_mm'] == before
    field.setText(canvas._distance_texts[0])
    qtbot.keyClick(field, Qt.Key.Key_Return)
    assert dialog._bend_editor.values()['front']['vertex_mm'] == before
    field.setText('100')
    canvas._dimension_fields[0].setText('50')
    qtbot.keyClick(field, Qt.Key.Key_Return)
    assert 'остальные' in canvas._dimension_error.text()
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    assert 'расстояния' in canvas._dimension_error.text()
    assert dialog._bend_editor.values()['front']['vertex_mm'] == before
    dialog.close()


def test_zero_projection_has_no_guessed_direction(qtbot):
    canvas = SkeletonProjection((0, 1))
    qtbot.addWidget(canvas)
    anchor, ball, point = (1., 2., 3.), (10., 20., 30.), (1., 2., 8.)
    canvas.set_preview(SkeletonPreview(((anchor, ball), (anchor, ball)), (anchor, anchor, ball)),
                       (('bend_front', point),))
    canvas.select_point('bend_front')
    emitted = []
    canvas.dimensionsApplied.connect(lambda *args: emitted.append(args))
    canvas._distance_fields[0].setText('5')
    canvas._apply_distance(0)
    assert not emitted and 'не определено' in canvas._dimension_error.text()


def test_project_change_during_input_invalidates_preview(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    dialog._point_picked('bend_front')
    before = dialog._bend_editor.values()
    canvas._distance_fields[0].setText('120')
    controller.project.front.hardpoints['lbj'].x += .000001
    qtbot.keyClick(canvas._distance_fields[0], Qt.Key.Key_Return)
    assert dialog._bend_editor.values() == before and dialog.preview is None and dialog.snapshot is None
    dialog.close()


def test_draft_radius_cancel_does_not_apply_distance(qtbot, monkeypatch):
    controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._bend_editor.checks['front'].setChecked(False)
    dialog._tabs.setCurrentIndex(1)
    a, b = dialog.preview.anchors[0], dialog.preview.anchors[2]
    point = tuple((a[i] + b[i]) / 2 for i in range(3))
    dialog._create_draft('front', point)
    canvas = dialog._projections[0]
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (0, False))
    old = dialog._draft
    canvas._distance_fields[0].setText(str(hypot(point[0] - a[0], point[1] - a[1]) * 1.2))
    qtbot.keyClick(canvas._distance_fields[0], Qt.Key.Key_Return)
    assert dialog._draft == old and not dialog._bend_editor.values()
    assert dialog.isVisible() and dialog.snapshot.matches(controller.project)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.close()


def test_distance_rejects_invalid_geometry_and_reset_discards_input(qtbot, monkeypatch):
    _, dialog = setup_dialog(qtbot, monkeypatch, vertex_z=140.)
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    dialog._point_picked('bend_front')
    original = dialog._bend_editor.values()
    canvas._distance_fields[0].setText('0.01')
    qtbot.keyClick(canvas._distance_fields[0], Qt.Key.Key_Return)
    assert dialog._bend_editor.values() == original and 'не принято' in dialog._selection_status.text()
    canvas._dimension_fields[0].setText('nan')
    canvas._reset_dimensions()
    assert tuple(field.text() for field in canvas._distance_fields) == canvas._distance_texts
    assert tuple(field.text() for field in canvas._dimension_fields) == canvas._dimension_texts
    assert dialog._bend_editor.values() == original
    dialog.close()


def test_distance_saves_exact_vertex_and_reopens(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    from suspensionlab.model.fixed_arm_skeleton_io import read_skeleton

    controller, dialog = setup_dialog(qtbot, monkeypatch)
    dialog._tabs.setCurrentIndex(1)
    canvas = dialog._projections[0]
    dialog._point_picked('bend_front')
    field = canvas._distance_fields[1]
    field.setText(str(float(field.text()) * 1.05))
    qtbot.keyClick(field, Qt.Key.Key_Return)
    vertex = dialog._bend_editor.values()['front']['vertex_mm']
    path = tmp_path / 'projection.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    assert path.exists() and read_skeleton(path, controller.project).bends['front']['vertex_mm'] == vertex
    dialog.close()
