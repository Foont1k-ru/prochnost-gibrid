"""Переходы из актуальной выбранной CAD-детали в параметры и проекцию."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu
from test_ball_housing_io_ui import parameters
from test_fixed_arm_housings import housings
from test_fixed_arm_tube_joint_ui import make_editor
from test_free_arm_inner_housings import make_inner

from suspensionlab.ui.free_arm_dialog import FreeArmDialog


def choose(qtbot, monkeypatch, cad, part, text, *, before=None):
    mesh = cad._view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index(part))[0])

    def select():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text().startswith(text))
        assert action.isEnabled()
        if before is not None:
            before()
        qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())

    QTimer.singleShot(50, select)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))


def free_editor(qtbot, monkeypatch, *, bent=(), ball=False, cuts=False, register=True):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    draft = make_inner(bent=bent, ball=ball, cuts=cuts)
    dialog = FreeArmDialog()
    if register:
        qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(draft.arm)
    dialog._set_housing_fields(draft.ball_housing)
    dialog._set_inner_fields(draft.housings)
    dialog.show()
    dialog.apply_fields()
    dialog._tabs.setCurrentWidget(dialog._cad)
    dialog._cad._quality.setCurrentIndex(1)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    return dialog, draft


@pytest.mark.parametrize('leg', ['front', 'rear'])
def test_free_housing_and_tube_go_to_selected_parameters_without_modification(qtbot, monkeypatch, leg):
    dialog, draft = free_editor(qtbot, monkeypatch, ball=True)
    cad = dialog._cad
    mesh, generation, form = cad._view.mesh, cad.generation, dialog._form()
    dialog._settings_toggle.setChecked(False)
    choose(qtbot, monkeypatch, cad, f'housing_{leg}', 'Параметры выбранного')
    assert dialog._settings_toggle.isChecked() and dialog._parameters_scroll.isVisible()
    assert QApplication.focusWidget() is dialog._fields[f'{leg}_inner_outer']
    assert dialog._form() == form and cad._view.mesh is mesh and cad.generation == generation
    dialog._settings_toggle.setChecked(False)
    choose(qtbot, monkeypatch, cad, f'tube_{leg}', 'Подрезка по своему')
    assert QApplication.focusWidget() is dialog._inner_notch[leg]
    assert not dialog._inner_notch[leg].isChecked() and dialog.inner_housings == draft.housings
    assert dialog._form() == form and cad._view.mesh is mesh
    dialog.close()


def test_existing_notch_goes_to_clearance_and_stale_menu_does_nothing(qtbot, monkeypatch):
    dialog, draft = free_editor(qtbot, monkeypatch, cuts=True)
    cad = dialog._cad
    dialog._settings_toggle.setChecked(False)
    choose(qtbot, monkeypatch, cad, 'tube_front', 'Подрезка по своему')
    assert QApplication.focusWidget() is dialog._fields['front_inner_clearance']
    assert dialog.inner_housings == draft.housings
    dialog._settings_toggle.setChecked(False)
    choose(qtbot, monkeypatch, cad, 'housing_rear', 'Параметры выбранного',
           before=lambda: dialog._fields['rear_inner_outer'].setText('53'))
    assert not dialog._settings_toggle.isChecked()
    assert cad._view.mesh is None and dialog.inner_housings == draft.housings
    dialog.close()


@pytest.mark.parametrize('bent', [False, True])
def test_free_tube_to_projection_keeps_accepted_geometry_until_apply(qtbot, monkeypatch, bent):
    dialog, draft = free_editor(qtbot, monkeypatch, bent=('front',) if bent else ())
    choose(qtbot, monkeypatch, dialog._cad, 'tube_front', 'Форма и изгиб на проекции')
    assert dialog._tabs.currentWidget() is dialog._projections[0]
    session = dialog._projection_session
    assert session is not None and session.code == 'bend_front'
    assert (session.new_vertex is None) == bent
    assert dialog.draft == draft.arm and dialog.inner_housings == draft.housings
    assert not dialog._save.isEnabled()
    dialog._close_projection_session()
    assert dialog.draft == draft.arm and dialog.inner_housings == draft.housings
    assert dialog._save.isEnabled()
    dialog.close()


@pytest.mark.parametrize('part', ['housing_front', 'housing_rear', 'ball_housing'])
def test_snapshot_housing_reveals_existing_control_without_edits(qtbot, monkeypatch, part):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_editor(qtbot, monkeypatch)
    dialog._housings = housings()
    dialog._ball_housing = parameters()
    dialog._refresh()
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    original, mesh, generation = dialog._state(), cad._view.mesh, cad.generation
    dialog._settings_toggle.setChecked(False)
    choose(qtbot, monkeypatch, cad, part, 'Параметры')
    expected = dialog._ball_edit if part == 'ball_housing' else dialog._housing_edit
    assert dialog._settings_toggle.isChecked() and dialog.focusWidget() is expected
    assert dialog._state() == original and cad._view.mesh is mesh and cad.generation == generation
    assert dialog.shutdown()
    dialog.close()


def test_snapshot_housing_menu_rejects_changed_project(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_editor(qtbot, monkeypatch)
    dialog._housings = housings()
    dialog._refresh()
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    dialog._settings_toggle.setChecked(False)
    def mutate():
        controller.project.front.hardpoints['lbj'].x += 1
    choose(qtbot, monkeypatch, cad, 'housing_front', 'Параметры', before=mutate)
    assert not dialog._settings_toggle.isChecked()
    assert dialog.shutdown()
    dialog.close()


@pytest.mark.parametrize('mode', ['independent', 'snapshot'])
def test_closing_and_deleting_owner_during_housing_menu_is_safe(qtbot, monkeypatch, mode):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    if mode == 'independent':
        dialog, _ = free_editor(qtbot, monkeypatch, register=False)
    else:
        from suspensionlab.model.templates import load_template
        from suspensionlab.ui.controller import AppController
        from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog

        pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
        controller = AppController()
        controller.project = load_template('ring')
        dialog = FixedArmSkeletonDialog(controller)
        dialog.show()
        dialog._capture_snapshot()
        dialog._tabs.setCurrentIndex(4)
        dialog._housings = housings()
        dialog._refresh()
        dialog._cad._enable.setChecked(True)
        qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
        monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    cad = dialog._cad
    mesh = cad._view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('housing_front'))[0])

    def close():
        assert isinstance(QApplication.activePopupWidget(), QMenu)
        dialog.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    QTimer.singleShot(50, close)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert not isValid(dialog)


def test_degenerate_xy_from_cad_explains_and_preserves_draft(qtbot, monkeypatch):
    from suspensionlab.model.free_arm import FreeArmDraft

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    draft = FreeArmDraft((0, 0, 0), (100, 0, 100), (0, 0, 300), 10, 2)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(draft)
    dialog.show()
    dialog.apply_fields()
    dialog._tabs.setCurrentWidget(dialog._cad)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    choose(qtbot, monkeypatch, dialog._cad, 'tube_front', 'Форма и изгиб на проекции')
    assert dialog._tabs.currentWidget() is dialog._projections[0]
    assert dialog._projection_session is None and dialog.draft == draft
    assert 'другую проекцию' in dialog._projection_note.text()
    assert dialog._save.isEnabled()
    dialog.close()


def test_unavailable_inner_notch_is_explicit_in_menu(qtbot, monkeypatch):
    from suspensionlab.model.free_arm import FreeArmDraft

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    draft = FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(draft)
    dialog.show()
    dialog.apply_fields()
    dialog._tabs.setCurrentWidget(dialog._cad)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    cad = dialog._cad
    mesh = cad._view.mesh
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index('tube_front'))[0])

    def inspect():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text().startswith('Подрезка недоступна'))
        assert not action.isEnabled() and 'корпуса не заданы' in action.text()
        menu.close()

    QTimer.singleShot(50, inspect)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert dialog.draft == draft and dialog.inner_housings is None and cad._view.mesh is mesh
    dialog.close()


@pytest.mark.parametrize('mode', ['independent', 'snapshot'])
@pytest.mark.parametrize('part,target', [('housing_front', 'housing_rear'), ('tube_front', 'tube_rear')])
def test_selection_change_during_menu_never_edits_previously_clicked_part(qtbot, monkeypatch, mode, part, target):
    if mode == 'independent':
        dialog, _ = free_editor(qtbot, monkeypatch)
    else:
        pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
        _, dialog = make_editor(qtbot, monkeypatch)
        dialog._housings = housings()
        dialog._refresh()
        dialog._cad._enable.setChecked(True)
        qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
    cad = dialog._cad
    dialog._settings_toggle.setChecked(False)
    mesh = cad._view.mesh
    target_index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index(target))[0])
    text = 'Редактировать эскиз' if part.startswith('tube_') else 'Параметры'
    choose(qtbot, monkeypatch, cad, part, text, before=lambda: cad._view.triangle_picked.emit(target_index))
    assert not dialog._settings_toggle.isChecked() and dialog._inline_session is None
    assert cad._view.mesh is mesh and cad._ready
    if mode == 'snapshot':
        assert dialog.shutdown()
    dialog.close()
