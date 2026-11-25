"""Длина независимой оси: контекст, валидность, актуальность и сохранение."""
from math import dist

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QFileDialog, QInputDialog, QMenu, QMessageBox
from test_free_arm_ball_housing_cad import independent
from test_free_arm_housing_ui import dialog_with_housing

from suspensionlab.model.bent_tube import make_bend_path
from suspensionlab.model.free_arm_io import read_free_arm
from suspensionlab.ui.free_arm_dialog import FreeArmDialog
from suspensionlab.ui.main_window import MainWindow


def ready(qtbot, monkeypatch, bends=('front', 'rear')):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(independent(bends))
    dialog.show()
    dialog.apply_fields()
    dialog._tabs.setCurrentWidget(dialog._cad)
    dialog._cad._quality.setCurrentIndex(1)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    return dialog


def length_of(draft, leg):
    bend = getattr(draft, leg + '_bend')
    start = getattr(draft, leg + '_mm')
    return make_bend_path(start, bend.vertex_mm, draft.outer_mm, bend.radius_mm, draft.radius_mm).length


def choose_length(qtbot, monkeypatch, dialog, leg, callback=None):
    view = dialog._cad._view
    mesh = view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('tube_' + leg))[0])

    def choose():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text().startswith('Длина осевой линии'))
        assert action.isEnabled()
        if callback is not None:
            callback()
        qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())

    QTimer.singleShot(50, choose)
    with monkeypatch.context() as patch:
        patch.setattr(view, '_pick_index', lambda *_args: index)
        qtbot.mouseClick(view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))


@pytest.mark.parametrize('leg', ['front', 'rear'])
def test_context_length_updates_only_chosen_bend_and_saves(qtbot, monkeypatch, tmp_path, leg):
    dialog = ready(qtbot, monkeypatch)
    before = dialog.draft
    target = length_of(before, leg) + 10
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_args: (target, True))
    choose_length(qtbot, monkeypatch, dialog, leg)
    after = dialog.draft
    assert after is not before and after.anchors == before.anchors
    assert after.radius_mm == before.radius_mm and after.wall_mm == before.wall_mm
    other = 'rear' if leg == 'front' else 'front'
    assert getattr(after, other + '_bend') == getattr(before, other + '_bend')
    old_bend, new_bend = getattr(before, leg + '_bend'), getattr(after, leg + '_bend')
    assert new_bend.radius_mm == old_bend.radius_mm
    start, end = np.array(getattr(before, leg + '_mm')), np.array(before.outer_mm)
    axis = (end - start) / np.linalg.norm(end - start)
    old_offset = np.array(old_bend.vertex_mm) - start
    new_offset = np.array(new_bend.vertex_mm) - start
    assert float(np.dot(old_offset, axis)) == pytest.approx(float(np.dot(new_offset, axis)), abs=1e-6)
    old_side = old_offset - np.dot(old_offset, axis) * axis
    new_side = new_offset - np.dot(new_offset, axis) * axis
    assert float(np.dot(old_side, new_side)) > 0
    assert np.linalg.norm(np.cross(old_side, new_side)) < 1e-6
    assert length_of(after, leg) == pytest.approx(target, abs=1e-5)
    assert dialog._cad._view.mesh is None and dialog._cad._document['bends'][leg]['vertex_mm'] == list(
        getattr(after, leg + '_bend').vertex_mm)
    path = tmp_path / 'length.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *_: (str(path), ''))
    dialog._save_file()
    assert read_free_arm(path) == after
    qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    assert dialog._cad._view.mesh is not None
    dialog.close()


def test_cancel_rounding_invalid_and_straight(qtbot, monkeypatch):
    dialog = ready(qtbot, monkeypatch, ('front',))
    before, mesh, generation = dialog.draft, dialog._cad._view.mesh, dialog._cad.generation
    warnings, info = [], []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: info.append(args[2]))
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (300, False))
    dialog._edit_tube_length('front')
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (round(length_of(before, 'front'), 4), True))
    dialog._edit_tube_length('front')
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: (dist(before.front_mm, before.outer_mm), True))
    dialog._edit_tube_length('front')
    dialog._edit_tube_length('rear')
    assert len(warnings) == 1 and len(info) == 1 and 'направление' in info[0]
    assert dialog.draft is before and dialog._cad.generation == generation and dialog._cad._view.mesh is mesh
    dialog.close()


@pytest.mark.parametrize('change', ['form', 'tab', 'inline', 'shutdown'])
def test_change_during_length_dialog_does_not_apply(qtbot, monkeypatch, change):
    dialog = ready(qtbot, monkeypatch)
    before = dialog.draft

    def stale(*_args):
        if change == 'form':
            dialog._fields['front_X'].setText('5')
        elif change == 'tab':
            dialog._tabs.setCurrentWidget(dialog._projections[0])
        elif change == 'inline':
            dialog._open_inline_sketch('rear')
            dialog._inline_sketch.fields['R'].setText('25')
        else:
            assert dialog.shutdown()
        return length_of(before, 'front') + 10, True

    monkeypatch.setattr(QInputDialog, 'getDouble', stale)
    dialog._edit_tube_length('front')
    assert dialog.draft is before
    if change == 'inline':
        assert dialog._inline_session is not None and dialog._inline_sketch.fields['R'].text() == '25'
    dialog.close()


def test_window_destroyed_during_length_prompt_does_not_apply(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._open_free_arm()
    dialog = window._free_arm_dialog
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(independent(('front',)))
    dialog.apply_fields()
    dialog._tabs.setCurrentWidget(dialog._cad)
    dialog._cad._quality.setCurrentIndex(1)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    before = dialog.draft

    def close_while_prompted(*_args):
        dialog.close()
        assert window._free_arm_dialog is None and dialog._cad._closed
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return length_of(before, 'front') + 10, True

    monkeypatch.setattr(QInputDialog, 'getDouble', close_while_prompted)
    dialog._edit_tube_length('front')
    assert dialog.draft is before
    monkeypatch.setattr(window, '_confirm_discard_changes', lambda: True)
    window.close()


def test_stale_context_menu_does_not_open_length_dialog(qtbot, monkeypatch):
    dialog = ready(qtbot, monkeypatch)
    before = dialog.draft
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: pytest.fail('stale menu opened a dialog'))
    choose_length(qtbot, monkeypatch, dialog, 'front', lambda: dialog._fields['front_X'].setText('5'))
    assert dialog.draft is before and dialog._cad._view.mesh is None
    dialog.close()


def test_housing_disables_length_and_preserves_model(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    dialog, data = dialog_with_housing(qtbot, monkeypatch, ('front',))
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    index = int(np.flatnonzero(cad._view.mesh.triangle_parts == cad._view.mesh.part_names.index('tube_front'))[0])

    def inspect_menu():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text().startswith('Длина осевой линии'))
        assert not action.isEnabled() and 'корпусом' in action.text()
        menu.close()

    QTimer.singleShot(50, inspect_menu)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *_: pytest.fail('housing must disable length'))
    dialog._edit_tube_length('front')
    assert dialog.draft == data.arm and dialog.housing == data.housing
    dialog.close()


def test_real_length_input_dialog_and_selection(qtbot, monkeypatch):
    dialog = ready(qtbot, monkeypatch)
    before = dialog.draft
    target = round(length_of(before, 'front') + 10, 4)

    def input_length():
        box = QApplication.activeModalWidget()
        assert isinstance(box, QInputDialog)
        available = box.screen().availableGeometry()
        assert box.width() <= available.width() and box.height() <= available.height()
        field = box.findChild(QDoubleSpinBox)
        assert field is not None and field.isVisible()
        field.setValue(target)
        box.accept()

    QTimer.singleShot(100, input_length)
    choose_length(qtbot, monkeypatch, dialog, 'front')
    assert length_of(dialog.draft, 'front') == pytest.approx(target, abs=1e-5)
    dialog.close()
