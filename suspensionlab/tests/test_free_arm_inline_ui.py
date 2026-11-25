"""Контекстный эскиз независимого рычага не изменяет опоры и не принимает устаревший CAD."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget
from test_free_arm_ui import fill

from suspensionlab.model.free_arm_io import read_free_arm, write_free_arm
from suspensionlab.ui.free_arm_dialog import FreeArmDialog
from suspensionlab.ui.inline_tube_sketch import InlineTubeSketch


def test_inline_fields_reflow_without_losing_input(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(600, 400)
    parent.show()
    editor = InlineTubeSketch(parent)
    editor.begin('front', (1, 2, 3), 20)
    editor.fields['X'].setText('12.5')
    assert not editor._compact
    parent.resize(320, 400)
    qtbot.waitUntil(lambda: editor._compact)
    assert editor.x() + editor.width() <= parent.width()
    assert editor.fields['X'].text() == '12.5'
    assert editor._grid.getItemPosition(editor._grid.indexOf(editor.fields['Z']))[:2] == (3, 0)
    parent.resize(600, 400)
    qtbot.waitUntil(lambda: not editor._compact)
    assert editor.fields['X'].text() == '12.5'
    assert editor._grid.getItemPosition(editor._grid.indexOf(editor.fields['Z']))[:2] == (1, 2)


def test_short_view_scrolls_without_clipping_or_losing_input(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(320, 170)
    parent.show()
    editor = InlineTubeSketch(parent)
    editor.begin('front', (1, 2, 3), None)
    editor.fields['X'].setText('12.5')
    qtbot.waitUntil(lambda: editor._scroll.verticalScrollBar().maximum() > 0)
    assert editor.x() + editor.width() <= parent.width()
    assert editor.y() + editor.height() <= parent.height()
    editor.fields['R'].setFocus()
    editor._scroll.ensureWidgetVisible(editor.fields['R'])
    assert editor._scroll.verticalScrollBar().value() > 0
    assert editor.fields['X'].text() == '12.5'
    parent.resize(600, 400)
    qtbot.waitUntil(lambda: not editor._compact)
    assert editor.fields['X'].text() == '12.5'
    assert editor.y() + editor.height() <= parent.height()


def ready_dialog(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    fill(dialog)
    dialog.apply_fields()
    dialog._tabs.setCurrentWidget(dialog._cad)
    dialog._cad._quality.setCurrentIndex(1)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    return dialog


def click_context_action(dialog, qtbot, monkeypatch, leg, before_click=None):
    view = dialog._cad._view
    mesh = view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('tube_' + leg))[0])

    def choose():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        if before_click is not None:
            before_click()
        action = next(a for a in menu.actions() if a.text() == 'Редактировать эскиз на модели')
        qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())

    QTimer.singleShot(50, choose)
    with monkeypatch.context() as patch:
        patch.setattr(view, '_pick_index', lambda *_args: index)
        qtbot.mouseClick(view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))


@pytest.mark.parametrize('leg', ['front', 'rear'])
def test_right_click_edit_apply_save_and_reopen(qtbot, monkeypatch, tmp_path, leg):
    dialog = ready_dialog(qtbot, monkeypatch)
    before = dialog.draft
    click_context_action(dialog, qtbot, monkeypatch, leg)
    editor = dialog._inline_sketch
    assert editor.isVisible() and editor.parent() is dialog._cad._view
    assert editor.x() >= 0 and editor.y() >= 0
    assert editor.x() + editor.width() <= dialog._cad._view.width()
    assert editor.y() + editor.height() <= dialog._cad._view.height()
    assert dialog._cad._view._sketch_path and not dialog._save.isEnabled()
    assert not dialog._cad._parts_tree.isEnabled() and not dialog._cad._parts_filter.isEnabled()
    editor.fields['R'].setText('20')
    assert not dialog._cad._view._sketch_path  # straight midpoint does not define a bend
    editor.fields['Z'].setText(str(float(editor.fields['Z'].text()) + 50))
    qtbot.wait(0)
    assert editor.x() + editor.width() <= dialog._cad._view.width()
    assert editor.y() + editor.height() <= dialog._cad._view.height()
    assert dialog._cad._view._sketch_path and dialog._cad._view._sketch_vertex is not None
    assert dialog.draft is before
    dialog._cad._view.yaw += .25
    dialog._cad._view.zoom = 1.5
    dialog.resize(1140, 780)
    dialog._cad._view.grab()  # paint the preview overlay after camera and size changes
    assert dialog._inline_current()
    qtbot.keyClick(editor.fields['R'], Qt.Key.Key_Return)
    assert not editor.isVisible() and dialog._cad._view.mesh is None
    assert dialog._cad._parts_tree.isEnabled() and dialog._cad._parts_filter.isEnabled()
    assert dialog.draft.anchors == before.anchors
    assert getattr(dialog.draft, leg + '_bend').radius_mm == 20
    assert dialog._bend_checks[leg].isChecked()
    assert dialog._save.isEnabled()
    path = tmp_path / f'{leg}.slarm'
    write_free_arm(path, dialog.draft)
    assert read_free_arm(path) == dialog.draft
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    click_context_action(dialog, qtbot, monkeypatch, leg)
    assert float(editor.fields['R'].text()) == 20
    assert tuple(float(editor.fields[axis].text()) for axis in 'XYZ') == getattr(dialog.draft, leg + '_bend').vertex_mm
    qtbot.keyClick(editor.fields['R'], Qt.Key.Key_Escape)
    assert dialog.shutdown()
    dialog.close()


def test_cancel_invalid_stale_and_selection(qtbot, monkeypatch):
    dialog = ready_dialog(qtbot, monkeypatch)
    before = dialog.draft
    click_context_action(dialog, qtbot, monkeypatch, 'front')
    editor = dialog._inline_sketch
    editor.fields['R'].setText('nan')
    qtbot.keyClick(editor.fields['R'], Qt.Key.Key_Return)
    assert editor.isVisible() and dialog.draft is before
    # Selecting the other part must not retarget the open editor or discard its input.
    mesh = dialog._cad._view.mesh
    rear_index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('tube_rear'))[0])
    dialog._cad._pick_tree_part(rear_index)
    assert editor.isVisible() and dialog._inline_session[0] == 'front'
    assert dialog._cad._parts_tree.currentItem().data(0, Qt.ItemDataRole.UserRole) == mesh.part_names.index('tube_front')
    qtbot.keyClick(editor.fields['R'], Qt.Key.Key_Escape)
    assert not editor.isVisible() and dialog.draft is before and dialog._save.isEnabled()
    dialog._open_inline_sketch('front')
    dialog._fields['front_X'].setText('25')
    assert not editor.isVisible() and not dialog._cad._view._sketch_path and dialog.draft is before
    assert not dialog._save.isEnabled()
    dialog.apply_fields()
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    assert dialog.draft.front_mm[0] == 25
    assert dialog.shutdown()
    dialog.close()


def test_menu_and_save_do_not_accept_stale_or_unapplied_input(qtbot, monkeypatch, tmp_path):
    dialog = ready_dialog(qtbot, monkeypatch)
    before = dialog.draft
    click_context_action(dialog, qtbot, monkeypatch, 'front',
                         before_click=lambda: dialog._fields['front_X'].setText('40'))
    assert not dialog._inline_sketch.isVisible() and dialog.draft is before
    dialog._restore_draft()
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    # Use saved form to distinguish unsaved inline edits from saved document fields.
    dialog._saved_form = dialog._form()
    dialog._open_inline_sketch('front')
    dialog._inline_sketch.fields['R'].setText('20')
    called = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *_args: called.append(True) or QMessageBox.StandardButton.No)
    assert not FreeArmDialog.confirm_close(dialog) and called
    monkeypatch.setattr('suspensionlab.ui.free_arm_dialog.QFileDialog.getSaveFileName',
                        lambda *_args: pytest.fail('unapplied inline edit cannot be saved'))
    dialog._save_file()
    assert not list(tmp_path.iterdir())
    dialog._close_inline_sketch()
    assert FreeArmDialog.confirm_close(dialog)
    assert dialog.shutdown()
    dialog.close()


def test_inline_opened_during_save_dialog_does_not_write_old_draft(qtbot, monkeypatch, tmp_path):
    dialog = ready_dialog(qtbot, monkeypatch)
    path = tmp_path / 'must-not-exist.slarm'

    def open_inline_during_save(*_args):
        dialog._open_inline_sketch('front')
        dialog._inline_sketch.fields['R'].setText('20')
        return str(path), ''

    monkeypatch.setattr('suspensionlab.ui.free_arm_dialog.QFileDialog.getSaveFileName', open_inline_during_save)
    dialog._save_file()
    assert dialog._inline_sketch.isVisible() and not path.exists()
    dialog._close_inline_sketch()
    assert dialog.shutdown()
    dialog.close()


def test_replaced_mesh_invalidates_inline_even_without_generation_change(qtbot, monkeypatch):
    from suspensionlab.core.cad_mesh import CadMesh

    dialog = ready_dialog(qtbot, monkeypatch)
    dialog._open_inline_sketch('front')
    before = dialog.draft
    old = dialog._cad._view.mesh
    replacement = CadMesh(old.triangles, old.face_count, part_names=old.part_names, triangle_parts=old.triangle_parts)
    generation = dialog._cad.generation
    dialog._cad._view.set_mesh(replacement)
    assert dialog._cad.generation == generation
    dialog._inline_sketch.fields['R'].setText('20')
    assert not dialog._inline_sketch.isVisible() and dialog.draft is before
    assert dialog.shutdown()
    dialog.close()


def test_right_click_miss_never_uses_previous_part(qtbot, monkeypatch):
    dialog = ready_dialog(qtbot, monkeypatch)
    view = dialog._cad._view
    root = dialog._cad._parts_tree.topLevelItem(0)
    dialog._cad._parts_tree.setCurrentItem(root.child(0))
    requested = []
    dialog._cad.partContextRequested.connect(lambda *args: requested.append(args))
    with monkeypatch.context() as patch:
        patch.setattr(view, '_pick_index', lambda *_args: None)
        qtbot.mouseClick(view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert not requested and not dialog._inline_sketch.isVisible()
    assert dialog.shutdown()
    dialog.close()
