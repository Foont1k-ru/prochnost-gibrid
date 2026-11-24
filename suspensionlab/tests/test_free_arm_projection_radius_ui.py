"""Радиус существующего изгиба в независимой проекции: атомарность и отмена."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from test_free_arm_projection_ui import select, setup

from suspensionlab.model.free_arm import FreeArmBend
from suspensionlab.model.free_arm_io import read_free_arm


@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('leg', ['front', 'rear'])
def test_edit_radius_preserves_geometry_and_roundtrip(qtbot, monkeypatch, tmp_path, index, leg):
    dialog, canvas = setup(qtbot, monkeypatch, index)
    before = dialog.draft
    original = getattr(before, f'{leg}_bend')
    select(qtbot, canvas, f'bend_{leg}', original.vertex_mm)
    assert dialog._projection_radius.isEnabled()
    assert dialog._projection_radius.text() == repr(original.radius_mm)
    dialog._projection_radius.setText('25,5')
    qtbot.keyClick(dialog._projection_radius, Qt.Key.Key_Return)
    after = dialog.draft
    result = getattr(after, f'{leg}_bend')
    assert result.radius_mm == 25.5 and result.vertex_mm == original.vertex_mm
    assert after.anchors == before.anchors and after.radius_mm == before.radius_mm and after.wall_mm == before.wall_mm
    other = 'rear' if leg == 'front' else 'front'
    assert getattr(after, f'{other}_bend') == getattr(before, f'{other}_bend')
    assert dialog._projection_session is None and not dialog._projection_radius.isEnabled()
    assert dialog._save.isEnabled() and dialog.isVisible()
    path = tmp_path / f'{leg}.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_free_arm(path) == after
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *_: (str(path), ''))
    dialog._open_file()
    assert dialog.draft == after
    dialog.close()


@pytest.mark.parametrize('value', ['', 'nan', 'inf', '-1', '0', '5', '1000001', 'abc', '1e999'])
def test_invalid_radius_keeps_applied_document(qtbot, monkeypatch, value):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    dialog._projection_radius.setText(value)
    qtbot.keyClick(dialog._projection_radius, Qt.Key.Key_Return)
    assert dialog.isVisible() and dialog.draft is before and canvas._dimension_error.isVisible()
    assert dialog._projection_session is not None and not dialog._save.isEnabled()
    dialog._reset_projection_radius()
    assert dialog._projection_radius.text() == repr(before.front_bend.radius_mm)
    dialog._close_projection_session()
    dialog.close()


def test_valid_number_impossible_geometry_and_cancel_close(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    dialog._projection_radius.setText('999999')
    qtbot.mouseClick(dialog._projection_radius_apply, Qt.MouseButton.LeftButton)
    assert dialog.draft is before and canvas._dimension_error.isVisible()
    dialog._saved_form = dialog._form()
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.No)
    assert not dialog.confirm_close()
    dialog._close_projection_session()
    assert dialog.draft is before and dialog._save.isEnabled()
    dialog.close()


def test_conflicting_inputs_never_discard_each_other(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    offset = canvas._dimension_fields[0]
    offset.setText(str(float(offset.text()) + 5))
    dialog._projection_radius.setText('25')
    qtbot.keyClick(dialog._projection_radius, Qt.Key.Key_Return)
    assert dialog.draft is before and 'смещения' in canvas._dimension_error.text()
    qtbot.keyClick(offset, Qt.Key.Key_Return)
    assert dialog.draft is before and 'радиус' in canvas._dimension_error.text()
    assert offset.text() != canvas._dimension_texts[0] and dialog._projection_radius.text() == '25'
    # Drag is also blocked while either field is dirty, without losing either edit.
    start = canvas._screen_point(before.front_bend.vertex_mm).toPoint()
    end = start + type(start)(15, -10)
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QApplication.sendEvent(canvas, QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(end),
                                               Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                               Qt.KeyboardModifier.NoModifier))
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert dialog.draft is before and dialog._projection_radius.text() == '25'
    dialog._reset_projection_radius()
    qtbot.keyClick(offset, Qt.Key.Key_Return)
    assert dialog.draft.front_bend.radius_mm == before.front_bend.radius_mm
    assert dialog.draft.front_bend.vertex_mm[0] == pytest.approx(before.front_bend.vertex_mm[0] + 5)
    dialog.close()


def test_radius_rejects_pending_distance_and_old_signal(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_rear', before.rear_bend.vertex_mm)
    canvas._distance_fields[1].setText('60')
    dialog._projection_radius.setText('25')
    qtbot.keyClick(dialog._projection_radius, Qt.Key.Key_Return)
    assert dialog.draft is before and canvas._distance_fields[1].text() == '60'
    canvas._reset_dimensions()  # Reset on canvas leaves radius input intact.
    assert dialog._projection_radius.text() == '25'
    qtbot.keyClick(dialog._projection_radius, Qt.Key.Key_Return)
    assert dialog.draft.rear_bend.radius_mm == 25
    newer = replace(dialog.draft, front_bend=FreeArmBend((155, 25, 50.123456789), 20))
    dialog._set_fields(newer)
    dialog._install(newer)
    dialog._apply_projection_radius()
    assert dialog.draft is newer
    dialog.close()


def test_no_radius_edit_for_new_draft_or_hidden_tab(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    dialog._projection_radius.setText('25')
    dialog._tabs.setTabEnabled(2, True)
    dialog._tabs.setCurrentIndex(2)
    dialog._apply_projection_radius()
    assert dialog.draft is before and dialog._projection_session is None
    dialog.close()


def test_new_vertex_radius_stays_in_creation_dialog(qtbot, monkeypatch):
    from test_free_arm_projection_create_ui import click_segment
    from test_free_arm_projection_create_ui import setup as setup_straight

    dialog, canvas = setup_straight(qtbot, monkeypatch)
    before = dialog.draft
    click_segment(qtbot, dialog, canvas, 'front')
    assert dialog._projection_session.new_vertex is not None
    assert not dialog._projection_radius.isEnabled() and not dialog._projection_radius_apply.isEnabled()
    dialog._apply_projection_radius()
    assert dialog.draft is before and dialog._projection_session is not None
    dialog._close_projection_session()
    dialog.close()


def test_radius_stale_and_mutated_during_close_confirmation(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    before = dialog.draft
    select(qtbot, canvas, 'bend_front', before.front_bend.vertex_mm)
    dialog._projection_radius.setText('25')
    dialog._saved_form = dialog._form()

    def change_radius(*_):
        dialog._projection_radius.setText('26')
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, 'question', change_radius)
    assert not dialog.confirm_close() and dialog.draft is before
    dialog._fields['front_X'].setText('1')
    assert dialog._projection_session is None
    dialog._apply_projection_radius()
    assert dialog.draft is before and dialog._accepted_form is None
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.close()


def test_radius_control_fits_window_at_small_size(qtbot, monkeypatch):
    dialog, canvas = setup(qtbot, monkeypatch)
    dialog.resize(800, 600)
    qtbot.wait(30)
    select(qtbot, canvas, 'bend_front', dialog.draft.front_bend.vertex_mm)
    for widget in (dialog._projection_radius, dialog._projection_radius_apply, dialog._projection_radius_reset):
        assert widget.isVisible() and dialog.rect().contains(widget.geometry())
    dialog._close_projection_session()
    dialog.close()


def test_radius_rebuilds_real_cad_and_rejects_old_job(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, canvas = setup(qtbot, monkeypatch)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._worker is not None, timeout=15000)
    token = dialog._cad.generation
    select(qtbot, canvas, 'bend_rear', dialog.draft.rear_bend.vertex_mm)
    dialog._projection_radius.setText('25')
    qtbot.keyClick(dialog._projection_radius, Qt.Key.Key_Return)
    assert dialog.draft.rear_bend.radius_mm == 25 and dialog._cad.generation > token
    assert dialog._cad._view.mesh is None
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=45000)
    assert dialog._cad._document['bends']['rear']['radius_mm'] == 25
    assert dialog._cad._view.mesh is not None
    dialog.close()
