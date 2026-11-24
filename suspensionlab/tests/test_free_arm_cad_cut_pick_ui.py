"""Независимый редактор: безопасный выбор второй CAD-детали для поддержанного реза."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMenu, QMessageBox
from test_arm_workspace_context_ui import free_editor
from test_free_arm_tube_joint_ui import select_joint

from suspensionlab.model.free_arm_housing_io import read_independent_arm
from suspensionlab.model.free_arm_tube_joint import FreeArmTubeJoint


def pick(cad, part):
    mesh = cad._view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index(part))[0])
    cad._view.triangle_picked.emit(index)


def start_cut(qtbot, monkeypatch, dialog, leg='front'):
    cad = dialog._cad
    mesh = cad._view.mesh
    part = f'tube_{leg}'
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index(part))[0])
    def choose():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        try:
            action = next(a for a in menu.actions() if a.text() == 'Обрезать по выбранному элементу…')
            assert action.isEnabled()
            qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
        finally:
            menu.close()
    QTimer.singleShot(50, choose)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert dialog._cad_cut_pick is not None and dialog._cad_cut_pick.part == part


@pytest.mark.parametrize('leg', ['front', 'rear'])
def test_choose_opposite_tube_miter_and_undo(qtbot, monkeypatch, leg, tmp_path):
    dialog, draft = free_editor(qtbot, monkeypatch)
    cad = dialog._cad
    start_cut(qtbot, monkeypatch, dialog, leg)
    assert dialog._cad_pick_controls.isVisible() and not dialog._trim_undo.isEnabled()
    cad._parts_tree.setCurrentItem(cad._parts_tree.topLevelItem(0).child(1))
    assert dialog._cad_cut_pick is not None and not dialog.miter  # Tree selection is not a pick.
    pick(cad, f'tube_{leg}')
    assert dialog._cad_cut_pick is not None and 'Другие резы' in dialog._cad_pick_status.text()
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.Yes)
    pick(cad, 'tube_rear' if leg == 'front' else 'tube_front')
    assert dialog._cad_cut_pick is None and dialog.miter and dialog.tube_joint is None
    assert dialog.inner_housings == draft.housings and cad._document['version'] == '4'
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    path = tmp_path / 'miter.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_independent_arm(path).housings == draft.housings
    dialog._undo_trim()
    assert not dialog.miter and dialog.tube_joint is None and cad._document['version'] == '3'
    dialog._redo_trim()
    assert dialog.miter and cad._document['version'] == '4'
    dialog.close()


@pytest.mark.parametrize('leg', ['front', 'rear'])
@pytest.mark.parametrize('ball', [False, True])
def test_choose_own_housing_preserves_other_parameters(qtbot, monkeypatch, leg, ball):
    dialog, draft = free_editor(qtbot, monkeypatch, ball=ball)
    cad = dialog._cad
    start_cut(qtbot, monkeypatch, dialog, leg)
    other = 'rear' if leg == 'front' else 'front'
    pick(cad, f'housing_{other}')
    assert dialog._cad_cut_pick is not None and 'Другие резы' in dialog._cad_pick_status.text()
    if ball:
        pick(cad, f'tube_{other}')
        assert dialog._cad_cut_pick is not None and 'центрального корпуса' in dialog._cad_pick_status.text()
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (1., True))
    pick(cad, f'housing_{leg}')
    assert dialog._cad_cut_pick is None and dialog.housing == draft.ball_housing
    assert getattr(dialog.inner_housings, f'{leg}_clearance_mm') == 1
    assert getattr(dialog.inner_housings, f'{other}_clearance_mm') is None
    assert cad._view.mesh is None and cad._document['version'] == '3'
    dialog._undo_trim()
    assert dialog.inner_housings == draft.housings and dialog.housing == draft.ball_housing
    dialog.close()


def test_replacing_one_sided_cut_requires_explicit_confirmation(qtbot, monkeypatch):
    dialog, _ = free_editor(qtbot, monkeypatch)
    select_joint(dialog, 'front', '.5')
    cad = dialog._cad
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    start_cut(qtbot, monkeypatch, dialog)
    prompts = []
    def deny(*args):
        prompts.append(args[2])
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, 'question', deny)
    pick(cad, 'tube_rear')
    assert 'заменена' in prompts[0] and dialog._cad_cut_pick is not None
    assert dialog.tube_joint == FreeArmTubeJoint('front', .5) and not dialog.miter
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.Yes)
    pick(cad, 'tube_rear')
    assert dialog.tube_joint is None and dialog.miter and cad._document['version'] == '4'
    dialog._undo_trim()
    assert dialog.tube_joint == FreeArmTubeJoint('front', .5) and not dialog.miter
    dialog.close()


def test_escape_cancel_and_change_of_tab_or_form(qtbot, monkeypatch):
    dialog, draft = free_editor(qtbot, monkeypatch)
    cad = dialog._cad
    start_cut(qtbot, monkeypatch, dialog)
    qtbot.keyClick(cad._view, Qt.Key.Key_Escape)
    assert dialog._cad_cut_pick is None and not dialog._cad_pick_controls.isVisible()
    assert dialog.draft == draft.arm and dialog.inner_housings == draft.housings
    start_cut(qtbot, monkeypatch, dialog)
    dialog._tabs.setCurrentWidget(dialog._projections[0])
    assert dialog._cad_cut_pick is None
    dialog._tabs.setCurrentWidget(cad)
    start_cut(qtbot, monkeypatch, dialog)
    dialog._fields['front_X'].setText('2')
    assert dialog._cad_cut_pick is None and cad._view.mesh is None and dialog.draft == draft.arm
    dialog.close()


@pytest.mark.parametrize('kind', ['form', 'selection', 'shutdown'])
def test_no_result_after_modal_becomes_stale(qtbot, monkeypatch, kind):
    dialog, draft = free_editor(qtbot, monkeypatch)
    cad = dialog._cad
    start_cut(qtbot, monkeypatch, dialog)
    def stale(*_):
        if kind == 'form':
            dialog._fields['front_X'].setText('5')
        elif kind == 'selection':
            root = cad._parts_tree.topLevelItem(0)
            cad._parts_tree.setCurrentItem(root.child(cad._view.mesh.part_names.index('housing_rear')))
        else:
            assert dialog.shutdown()
        return 1., True
    monkeypatch.setattr(QInputDialog, 'getDouble', stale)
    pick(cad, 'housing_front')
    assert dialog._cad_cut_pick is None and dialog.inner_housings == draft.housings
    assert dialog.draft == draft.arm and dialog.tube_joint is None and not dialog.miter
    dialog.close()


def test_bad_or_cancelled_clearance_does_not_change_document(qtbot, monkeypatch):
    dialog, draft = free_editor(qtbot, monkeypatch)
    cad = dialog._cad
    start_cut(qtbot, monkeypatch, dialog)
    for result in ((20., False), (float('nan'), True), (101., True), (-1., True)):
        monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_, result=result: result)
        pick(cad, 'housing_front')
        assert dialog._cad_cut_pick is not None and dialog.inner_housings == draft.housings
    dialog._cancel_cad_cut_pick()
    assert dialog._cad._document['notches'] is None
    dialog.close()


@pytest.mark.parametrize('operation', ['miter', 'housing'])
def test_deferred_owner_deletion_during_modal_does_not_apply(qtbot, monkeypatch, operation):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    dialog, _ = free_editor(qtbot, monkeypatch, register=False)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    cad = dialog._cad
    start_cut(qtbot, monkeypatch, dialog)
    def close(*_):
        dialog.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return QMessageBox.StandardButton.Yes if operation == 'miter' else (1., True)
    if operation == 'miter':
        monkeypatch.setattr(QMessageBox, 'question', close)
        pick(cad, 'tube_rear')
    else:
        monkeypatch.setattr(QInputDialog, 'getDouble', close)
        pick(cad, 'housing_front')
    assert not isValid(dialog)


def test_reentrant_pick_in_modal_does_not_open_nested_dialog(qtbot, monkeypatch):
    dialog, draft = free_editor(qtbot, monkeypatch)
    cad = dialog._cad
    start_cut(qtbot, monkeypatch, dialog)
    calls = []
    def nested(*_):
        calls.append(1)
        pick(cad, 'housing_front')
        return 1., True
    monkeypatch.setattr(QInputDialog, 'getDouble', nested)
    pick(cad, 'housing_front')
    assert calls == [1] and dialog.inner_housings.front_clearance_mm == 1
    assert dialog.inner_housings.rear == draft.housings.rear
    dialog.close()


def test_menu_explicitly_unavailable_if_only_central_housing(qtbot, monkeypatch):
    dialog, _ = free_editor(qtbot, monkeypatch, ball=True)
    dialog._set_inner_fields(None)
    dialog.apply_fields()
    cad = dialog._cad
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    mesh = cad._view.mesh
    triangle = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('tube_front'))[0])
    checked = []
    def inspect():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        try:
            action = next(a for a in menu.actions() if a.text().startswith('Выбор реза недоступен'))
            checked.append(not action.isEnabled() and 'центральный корпус' in action.text())
        finally:
            menu.close()
    QTimer.singleShot(50, inspect)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: triangle)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert checked == [True] and dialog._cad_cut_pick is None
    dialog.close()


def test_actual_left_click_on_visible_second_tube(qtbot, monkeypatch):
    from suspensionlab.core.cad_raster import pick_triangle, screen_projection

    dialog, _ = free_editor(qtbot, monkeypatch)
    cad = dialog._cad
    start_cut(qtbot, monkeypatch, dialog)
    view = cad._view
    ratio = view.devicePixelRatioF()
    width, height = round(view.width() * ratio), round(view.height() * ratio)
    offset = view._pixel_offset(width, height)
    projected, _ = screen_projection(view._triangles, view._center, view._radius, view.yaw, view.elevation,
                                     view.zoom, width, height, 24 * ratio, offset=offset)
    rear = view.mesh.part_names.index('tube_rear')
    point = None
    for i in np.flatnonzero(view.mesh.triangle_parts == rear):
        x, y = (int(v) for v in np.mean(projected[i], axis=0))
        if not (0 <= x < width and 0 <= y < height):
            continue
        hit = pick_triangle(view._triangles, view._center, view._radius, view.yaw, view.elevation,
                            view.zoom, width, height, x, y, margin=24 * ratio,
                            highlight=view._highlight, through=view._through, offset=offset)
        if hit is not None and view.mesh.triangle_parts[hit] == rear:
            point = QPoint(round(x / ratio), round(y / ratio))
            break
    assert point is not None
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.Yes)
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=point)
    assert dialog._cad_cut_pick is None and dialog.miter and cad._document['version'] == '4'
    dialog.close()


def test_existing_housing_cut_same_value_is_noop(qtbot, monkeypatch):
    dialog, draft = free_editor(qtbot, monkeypatch, cuts=True)
    cad = dialog._cad
    old_mesh, generation, history = cad._view.mesh, cad.generation, len(dialog._trim_history)
    start_cut(qtbot, monkeypatch, dialog)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (1., True))
    pick(cad, 'housing_front')
    assert dialog._cad_cut_pick is None and dialog.inner_housings == draft.housings
    assert cad._view.mesh is old_mesh and cad.generation == generation and len(dialog._trim_history) == history
    dialog.close()


@pytest.mark.parametrize('operation', ['miter', 'housing'])
def test_real_confirmation_fits_screen_and_cancel_is_safe(qtbot, monkeypatch, operation):
    from PySide6.QtWidgets import QDialog

    dialog, draft = free_editor(qtbot, monkeypatch)
    cad = dialog._cad
    start_cut(qtbot, monkeypatch, dialog)
    checked = []
    def cancel():
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, QDialog)
        try:
            screen = modal.screen().availableGeometry()
            checked.append(modal.width() <= screen.width() and modal.height() <= screen.height())
        finally:
            modal.reject()
    QTimer.singleShot(50, cancel)
    pick(cad, 'tube_rear' if operation == 'miter' else 'housing_front')
    assert checked == [True] and dialog._cad_cut_pick is not None
    assert dialog.draft == draft.arm and dialog.inner_housings == draft.housings and not dialog.miter
    qtbot.mouseClick(dialog._cad_pick_cancel, Qt.MouseButton.LeftButton)
    assert dialog._cad_cut_pick is None
    dialog.close()
