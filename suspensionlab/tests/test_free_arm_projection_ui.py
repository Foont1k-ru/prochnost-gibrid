"""Независимый рычаг: правка существующих изгибов в ортогональных проекциях."""
from math import hypot

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft
from suspensionlab.model.free_arm_io import read_free_arm
from suspensionlab.ui.free_arm_dialog import FreeArmDialog


def setup(qtbot, monkeypatch, index=0):
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.Yes)
    draft = FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2,
                         FreeArmBend((150, 20, 50.123456789), 20),
                         FreeArmBend((160, 180, -40.123456789), 20))
    dialog._set_fields(draft)
    dialog._install(draft)
    dialog.show()
    dialog._tabs.setCurrentIndex(index + 1)
    return dialog, dialog._projections[index]


def select(qtbot, canvas, code, point):
    pos = canvas._screen_point(point).toPoint()
    assert canvas._point_hits(QPointF(pos)) == (code,)
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pos)
    assert canvas.selected_point == code


def move(canvas, pos):
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), QPointF(pos), Qt.MouseButton.NoButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(canvas, event)


@pytest.mark.parametrize('index,axes', [(0, (0, 1)), (1, (0, 2)), (2, (1, 2))])
@pytest.mark.parametrize('leg', ['front', 'rear'])
def test_drag_and_roundtrip(qtbot, monkeypatch, tmp_path, index, axes, leg):
    dialog, canvas = setup(qtbot, monkeypatch, index)
    before = dialog.draft
    bend = getattr(before, f'{leg}_bend')
    assert bend is not None
    pos = canvas._screen_point(bend.vertex_mm).toPoint()
    assert canvas._point_hits(QPointF(pos)) == (f'bend_{leg}',)
    scale = canvas._transform()[2]
    size = canvas.size()
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    QApplication.processEvents()
    assert canvas.size() == size
    end = pos + type(pos)(8, -6)
    move(canvas, end)
    assert dialog.draft is before
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    after = dialog.draft
    new = getattr(after, f'{leg}_bend')
    hidden = ({0, 1, 2} - set(axes)).pop()
    assert new.vertex_mm[axes[0]] == pytest.approx(bend.vertex_mm[axes[0]] + 8 / scale)
    assert new.vertex_mm[axes[1]] == pytest.approx(bend.vertex_mm[axes[1]] + 6 / scale)
    assert new.vertex_mm[hidden] == bend.vertex_mm[hidden]
    assert new.radius_mm == bend.radius_mm and after.anchors == before.anchors
    other = 'rear' if leg == 'front' else 'front'
    assert getattr(after, f'{other}_bend') == getattr(before, f'{other}_bend')
    path = tmp_path / 'edited.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_free_arm(path) == after
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert dialog.draft == after and dict(dialog._projections[index].points)[f'bend_{leg}'] == new.vertex_mm
    dialog.close()


@pytest.mark.parametrize('index,axes', [(0, (0, 1)), (1, (0, 2)), (2, (1, 2))])
@pytest.mark.parametrize('leg', ['front', 'rear'])
def test_offsets_and_distance(qtbot, monkeypatch, index, axes, leg):
    dialog, canvas = setup(qtbot, monkeypatch, index)
    before = dialog.draft
    bend = getattr(before, f'{leg}_bend')
    select(qtbot, canvas, f'bend_{leg}', bend.vertex_mm)
    anchor = getattr(before, f'{leg}_mm')
    canvas._dimension_fields[0].setText(str(bend.vertex_mm[axes[0]] - anchor[axes[0]] + 5))
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    new = getattr(dialog.draft, f'{leg}_bend')
    hidden = ({0, 1, 2} - set(axes)).pop()
    assert new.vertex_mm[axes[0]] == pytest.approx(bend.vertex_mm[axes[0]] + 5)
    assert new.vertex_mm[hidden] == bend.vertex_mm[hidden]
    select(qtbot, canvas, f'bend_{leg}', new.vertex_mm)
    old_distance = hypot(*(new.vertex_mm[a] - anchor[a] for a in axes))
    canvas._distance_fields[0].setText(str(old_distance + 3))
    qtbot.keyClick(canvas._distance_fields[0], Qt.Key.Key_Return)
    final = getattr(dialog.draft, f'{leg}_bend')
    assert hypot(*(final.vertex_mm[a] - anchor[a] for a in axes)) == pytest.approx(old_distance + 3)
    assert final.vertex_mm[hidden] == bend.vertex_mm[hidden]
    assert dialog.draft.anchors == before.anchors and final.radius_mm == bend.radius_mm
    dialog.close()


def test_invalid_pending_cancel_stale_and_close(qtbot, monkeypatch, tmp_path):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    assert not dialog._save.isEnabled() and not dialog._parameter_panel.isEnabled()
    canvas._dimension_fields[0].setText('nan')
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    assert dialog.draft is before and canvas._dimension_error.isVisible()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: pytest.fail('must not save'))
    dialog._save_file()
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.No)
    dialog._saved_form = dialog._form()
    assert not dialog.confirm_close()
    dialog._close_projection_session()
    assert dialog.draft is before and dialog._save.isEnabled()
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    # Even a programmatic change invalidates the session before the old signal can apply.
    dialog._fields['front_X'].setText('1')
    canvas.dimensionsApplied.emit('bend_front', canvas.axes, (151., 20., 50.))
    assert dialog.draft is before and dialog._accepted_form is None
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()


def test_invalid_geometry_does_not_install(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    canvas._dimension_fields[0].setText('1000001')
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    assert dialog.draft is before and canvas._dimension_error.isVisible()
    assert dialog._projection_session is not None
    dialog._close_projection_session()
    dialog.close()


def test_pending_input_blocks_drag_and_switch_and_can_reset(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    canvas._dimension_fields[0].setText('123')
    pos = canvas._screen_point(before.front_bend.vertex_mm).toPoint()
    end = pos + type(pos)(12, 8)
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    move(canvas, end)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert dialog.draft is before and canvas._dimension_fields[0].text() == '123'
    other = canvas._screen_point(before.rear_bend.vertex_mm).toPoint()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=other)
    assert canvas.selected_point == 'bend_front' and dialog.draft is before
    assert not dialog._tabs.isTabEnabled(2) and not dialog._tabs.isTabEnabled(4)
    canvas._reset_dimensions()
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos)
    move(canvas, end)
    qtbot.keyClick(canvas, Qt.Key.Key_Escape)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert dialog.draft is before and dialog._projection_session is not None
    dialog._close_projection_session()
    assert all(dialog._tabs.isTabEnabled(i) for i in range(dialog._tabs.count()))
    dialog.close()


def test_stale_open_save_dialog_and_close_confirmation(qtbot, monkeypatch, tmp_path):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    path = tmp_path / 'save.slarm'

    def change_during_save(*_):
        dialog._projection_point(canvas, 'bend_front')
        return str(path), ''

    monkeypatch.setattr(QFileDialog, 'getSaveFileName', change_during_save)
    dialog._save_file()
    assert not path.exists() and dialog.draft is before
    canvas._dimension_fields[0].setText('222')
    dialog._saved_form = dialog._form()

    def mutate_during_question(*_):
        canvas._dimension_fields[0].setText('223')
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, 'question', mutate_during_question)
    assert not dialog.confirm_close()
    dialog._close_projection_session()
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()


def test_other_distance_and_geometric_failure(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    bend = before.front_bend
    select(qtbot, canvas, 'bend_front', bend.vertex_mm)
    reference = before.outer_mm
    old = hypot(*(bend.vertex_mm[a] - reference[a] for a in canvas.axes))
    canvas._distance_fields[1].setText(str(old + 3))
    qtbot.keyClick(canvas._distance_fields[1], Qt.Key.Key_Return)
    after = dialog.draft
    assert hypot(*(after.front_bend.vertex_mm[a] - reference[a] for a in canvas.axes)) == pytest.approx(old + 3)
    # A finite, in-range coordinate triple can still violate the bend construction.
    from dataclasses import replace
    planar = replace(after, front_bend=FreeArmBend((150, 20, 0), 20))
    dialog._set_fields(planar)
    dialog._install(planar)
    select(qtbot, canvas, 'bend_front', planar.front_bend.vertex_mm)
    canvas._dimension_fields[0].setText('0')
    canvas._dimension_fields[1].setText('0')
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    assert dialog.draft is planar and canvas._dimension_error.isVisible()
    dialog._close_projection_session()
    dialog.close()


def test_superseded_projection_and_conflicting_dimensions(qtbot, monkeypatch):
    from dataclasses import replace

    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    canvas._dimension_fields[0].setText('151')
    canvas._distance_fields[0].setText('100')
    qtbot.keyClick(canvas._dimension_fields[0], Qt.Key.Key_Return)
    assert dialog.draft is before and canvas._dimension_error.isVisible()
    # Replacing the model invalidates even a queued signal from the old projection.
    newer = replace(before, front_bend=FreeArmBend((155, 25, 50.123456789), 20))
    dialog._set_fields(newer)
    dialog._install(newer)
    assert dialog._projection_session is None
    canvas.dimensionsApplied.emit('bend_front', canvas.axes, (151., 20., 0.))
    assert dialog.draft is newer and dialog._candidate() == newer
    dialog.close()
