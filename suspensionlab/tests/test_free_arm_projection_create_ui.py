"""Создание изгиба независимого рычага на проекции без изменения принятой модели до проверки."""
from dataclasses import replace
from math import hypot

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft
from suspensionlab.model.free_arm_io import read_free_arm
from suspensionlab.ui.free_arm_dialog import FreeArmDialog


def setup(qtbot, monkeypatch, index=0, draft=None):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.Yes)
    if draft is None:
        draft = FreeArmDraft((0, 0, 0), (0, 220, 65), (320, 100, 140), 10, 2)
    dialog._set_fields(draft)
    dialog._install(draft)
    dialog.show()
    dialog._tabs.setCurrentIndex(index + 1)
    return dialog, dialog._projections[index]


def click_segment(qtbot, dialog, canvas, leg, fraction=0.5):
    draft = dialog.draft
    a = draft.front_mm if leg == 'front' else draft.rear_mm
    b = draft.outer_mm
    point = tuple(a[i] + fraction * (b[i] - a[i]) for i in range(3))
    pos = canvas._screen_point(point).toPoint()
    assert not canvas._point_hits(QPointF(pos))
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pos)
    return point


def move(canvas, pos):
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), QPointF(pos), Qt.MouseButton.NoButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(canvas, event)


def drag(qtbot, canvas, vertex, delta):
    start = canvas._screen_point(vertex).toPoint()
    end = start + delta
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    move(canvas, end)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)


@pytest.mark.parametrize('index,axes', [(0, (0, 1)), (1, (0, 2)), (2, (1, 2))])
@pytest.mark.parametrize('leg', ['front', 'rear'])
def test_create_with_drag_and_roundtrip(qtbot, monkeypatch, tmp_path, index, axes, leg):
    from PySide6.QtCore import QPoint

    dialog, canvas = setup(qtbot, monkeypatch, index)
    original = dialog.draft
    click_segment(qtbot, dialog, canvas, leg)
    session = dialog._projection_session
    assert session is not None and session.new_vertex is not None and session.code == f'bend_{leg}'
    assert dialog.draft is original and not dialog._save.isEnabled()
    assert canvas.preview.centerlines == original.centerlines()
    vertex = session.new_vertex
    scale = canvas._transform()[2]
    # The second visible coordinate moves away from the straight axis.
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (20., True))
    drag(qtbot, canvas, vertex, QPoint(0, -40))
    result = dialog.draft
    bend = getattr(result, f'{leg}_bend')
    assert bend is not None
    hidden = ({0, 1, 2} - set(axes)).pop()
    assert bend.vertex_mm[hidden] == vertex[hidden]
    assert bend.vertex_mm[axes[0]] == vertex[axes[0]]
    assert bend.vertex_mm[axes[1]] == pytest.approx(vertex[axes[1]] + 40 / scale)
    assert bend.radius_mm == 20 and result.anchors == original.anchors
    assert getattr(result, f"{'rear' if leg == 'front' else 'front'}_bend") is None
    assert dialog._projection_session is None and dialog._save.isEnabled()
    path = tmp_path / f'{leg}.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_free_arm(path) == result
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert dialog.draft == result
    dialog.close()


def test_create_by_offset_radius_cancel_invalid_then_valid(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    click_segment(qtbot, dialog, canvas, 'front')
    session = dialog._projection_session
    original = session.new_vertex
    anchor = before.front_mm
    canvas._dimension_fields[1].setText(str(original[1] - anchor[1] + 50))
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (0., False))
    qtbot.keyClick(canvas._dimension_fields[1], Qt.Key.Key_Return)
    assert dialog.draft is before and dialog._projection_session is session
    assert canvas._dimension_error.isVisible() and canvas._dimension_fields[1].text()
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (0., True))
    qtbot.keyClick(canvas._dimension_fields[1], Qt.Key.Key_Return)
    assert dialog.draft is before and canvas._dimension_error.isVisible()
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (20., True))
    qtbot.keyClick(canvas._dimension_fields[1], Qt.Key.Key_Return)
    assert dialog.draft.front_bend.vertex_mm[1] == pytest.approx(original[1] + 50)
    assert dialog.draft.front_bend.vertex_mm[2] == original[2]
    dialog.close()


def test_create_with_distance_and_preserve_other_bend(qtbot, monkeypatch):
    draft = FreeArmDraft((0, 0, 0), (0, 220, 65), (320, 100, 140), 10, 2,
                         rear_bend=FreeArmBend((160, 190, 180), 20))
    dialog, canvas = setup(qtbot, monkeypatch, draft=draft)
    click_segment(qtbot, dialog, canvas, 'front')
    session = dialog._projection_session
    old = session.new_vertex
    anchor = draft.front_mm
    distance = hypot(old[0] - anchor[0], old[1] - anchor[1])
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (20., True))
    # The initial point is on the 3D axis and cannot form a bend.
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    assert dialog.draft is draft and canvas._dimension_error.isVisible()
    canvas._distance_fields[0].setText(str(distance + 30))
    qtbot.keyClick(canvas._distance_fields[0], Qt.Key.Key_Return)
    assert dialog.draft.front_bend is not None and dialog.draft.rear_bend == draft.rear_bend
    new = dialog.draft.front_bend.vertex_mm
    assert hypot(new[0] - anchor[0], new[1] - anchor[1]) == pytest.approx(distance + 30)
    assert new[2] == old[2]
    dialog.close()


def test_cancel_draft_and_stale_radius(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    old_points = canvas.points
    dialog._saved_form = dialog._form()
    click_segment(qtbot, dialog, canvas, 'front')
    assert len(canvas.points) == len(old_points) + 1
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.No)
    assert not dialog.confirm_close()
    dialog._close_projection_session()
    assert canvas.points == old_points and dialog.draft is before and dialog._save.isEnabled()
    click_segment(qtbot, dialog, canvas, 'front')
    session = dialog._projection_session
    canvas._dimension_fields[1].setText('100')

    def mutate_input(*_):
        canvas._dimension_fields[1].setText('101')
        return 20., True

    monkeypatch.setattr(QInputDialog, 'getDouble', mutate_input)
    qtbot.keyClick(canvas._dimension_fields[1], Qt.Key.Key_Return)
    assert dialog.draft is before and dialog._projection_session is session
    assert canvas._dimension_fields[1].text() == '101' and canvas._dimension_error.isVisible()

    def replace_draft(*_):
        newer = replace(before, front_mm=(1., 0., 0.))
        dialog._set_fields(newer)
        dialog._install(newer)
        return 20., True

    monkeypatch.setattr(QInputDialog, 'getDouble', replace_draft)
    qtbot.keyClick(canvas._dimension_fields[1], Qt.Key.Key_Return)
    assert dialog.draft.front_mm == (1., 0., 0.) and dialog.draft.front_bend is None
    assert dialog._projection_session is None
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()


def test_new_session_does_not_clobber_newer_session_during_radius(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    click_segment(qtbot, dialog, canvas, 'front')
    canvas._dimension_fields[1].setText('100')

    def replace_session(*_):
        dialog._close_projection_session()
        click_segment(qtbot, dialog, canvas, 'rear')
        canvas._dimension_fields[1].setText('77')
        return 20., True

    monkeypatch.setattr(QInputDialog, 'getDouble', replace_session)
    qtbot.keyClick(canvas._dimension_fields[1], Qt.Key.Key_Return)
    assert dialog._projection_session.code == 'bend_rear'
    assert canvas._dimension_fields[1].text() == '77'
    assert dialog.draft.front_bend is None and dialog.draft.rear_bend is None
    dialog._close_projection_session()
    dialog.close()


def test_both_paths_overlap_or_invalid_segment_no_guess(qtbot, monkeypatch):
    draft = FreeArmDraft((0, 0, 0), (0, 0, 100), (320, 100, 140), 10, 2)
    dialog, canvas = setup(qtbot, monkeypatch, draft=draft)
    click_segment(qtbot, dialog, canvas, 'front')
    assert dialog._projection_session is None and dialog.draft is draft
    assert 'перекрываются' in dialog._projection_note.text()
    # Explicitly injected stale or off-segment points are also rejected.
    dialog._projection_segment(canvas, 'front', (123., 20., 5.))
    assert dialog._projection_session is None
    dialog.close()


def test_real_radius_dialog_and_displaced_marker(qtbot, monkeypatch):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QDoubleSpinBox

    dialog, canvas = setup(qtbot, monkeypatch)
    click_segment(qtbot, dialog, canvas, 'front')
    initial = dialog._projection_session.new_vertex
    seen = []

    def accept_radius():
        box = next(widget for widget in QApplication.topLevelWidgets() if isinstance(widget, QInputDialog))
        seen.append(box.labelText())
        box.findChild(QDoubleSpinBox).setValue(20.)
        box.accept()

    QTimer.singleShot(0, accept_radius)
    drag(qtbot, canvas, initial, QPoint(0, -40))
    assert seen and 'Скрытая Z' in seen[0] and 'интерполяция' in seen[0]
    assert dialog.draft.front_bend is not None and dialog.draft.front_bend.radius_mm == 20
    dialog.close()


def test_overlap_with_curved_other_path_is_ambiguous(qtbot, monkeypatch):
    draft = FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2,
                         rear_bend=FreeArmBend((160, 0, 30), 20))
    dialog, canvas = setup(qtbot, monkeypatch, draft=draft)
    # Find an intersection of the displayed bent path and the front XY segment.
    front_a = canvas._screen_point(draft.front_mm)
    front_b = canvas._screen_point(draft.outer_mm)
    front_x, front_y = front_b.x() - front_a.x(), front_b.y() - front_a.y()
    intersection = None
    path = canvas.preview.centerlines[1]
    for first, second in zip(path, path[1:], strict=False):
        a, b = canvas._screen_point(first), canvas._screen_point(second)
        dx, dy = b.x() - a.x(), b.y() - a.y()
        denom = front_x * dy - front_y * dx
        if abs(denom) < 1e-9:
            continue
        u = ((a.x() - front_a.x()) * dy - (a.y() - front_a.y()) * dx) / denom
        v = ((a.x() - front_a.x()) * front_y - (a.y() - front_a.y()) * front_x) / denom
        if 0.15 < u < 0.85 and 0 <= v <= 1:
            intersection = QPointF(front_a.x() + u * front_x, front_a.y() + u * front_y).toPoint()
            break
    assert intersection is not None and not canvas._point_hits(QPointF(intersection))
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=intersection)
    assert dialog._projection_session is None and dialog.draft is draft
    assert 'перекрываются' in dialog._projection_note.text()
    dialog.close()


def test_creation_rebuilds_real_cad_and_rejects_old_job(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, canvas = setup(qtbot, monkeypatch)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._worker is not None, timeout=15000)
    token = dialog._cad.generation
    click_segment(qtbot, dialog, canvas, 'front')
    original = dialog._projection_session.new_vertex
    canvas._dimension_fields[1].setText(str(original[1] + 50))
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (20., True))
    qtbot.keyClick(canvas._dimension_fields[1], Qt.Key.Key_Return)
    assert dialog.draft.front_bend is not None and dialog._cad.generation > token
    assert dialog._cad._view.mesh is None
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=45000)
    assert dialog._cad._document['bends']['front']['vertex_mm'] == list(dialog.draft.front_bend.vertex_mm)
    assert dialog._cad._view.mesh is not None and dialog._cad._view.mesh.part_names == ('tube_front', 'tube_rear')
    dialog.close()


def test_hidden_projection_cannot_start_or_finish_creation(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    point = tuple((a + b) / 2 for a, b in zip(before.front_mm, before.outer_mm, strict=True))
    dialog._tabs.setCurrentIndex(2)
    canvas.segmentPicked.emit('front', point)
    assert dialog._projection_session is None and dialog.draft is before
    dialog._tabs.setCurrentIndex(1)
    click_segment(qtbot, dialog, canvas, 'front')
    canvas._dimension_fields[1].setText('100')

    def change_tab_during_radius(*_):
        dialog._tabs.setTabEnabled(2, True)
        dialog._tabs.setCurrentIndex(2)
        return 20., True

    monkeypatch.setattr(QInputDialog, 'getDouble', change_tab_during_radius)
    qtbot.keyClick(canvas._dimension_fields[1], Qt.Key.Key_Return)
    assert dialog.draft is before and dialog._projection_session is None
    dialog.close()
