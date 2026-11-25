"""Переход из выбранной CAD-трубы к нужной проекции в двух редакторах."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu
from test_arm_workspace_context_ui import free_editor
from test_fixed_arm_tube_joint_ui import make_editor

from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft
from suspensionlab.ui.free_arm_dialog import FreeArmDialog


def choose_projection(qtbot, monkeypatch, dialog, leg, name, before=None):
    cad = dialog._cad
    mesh = cad._view.mesh
    part = f'tube_{leg}'
    index = int(np.flatnonzero(mesh.triangle_parts == mesh.part_names.index(part))[0])

    def open_submenu():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        parent = next(a for a in menu.actions() if a.menu() and
                      any(f'проекции {name}' in child.text() for child in a.menu().actions()))
        submenu = parent.menu()
        menu.setActiveAction(parent)
        qtbot.keyClick(menu, Qt.Key.Key_Right)
        def select():
            try:
                action = next(a for a in submenu.actions() if f'проекции {name}' in a.text())
                assert action.isEnabled()
                if before:
                    before()
                qtbot.mouseClick(submenu, Qt.MouseButton.LeftButton, pos=submenu.actionGeometry(action).center())
            finally:
                menu.close()
        QTimer.singleShot(50, select)

    QTimer.singleShot(50, open_submenu)
    with monkeypatch.context() as patch:
        patch.setattr(cad._view, '_pick_index', lambda *_: index)
        qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))


@pytest.mark.parametrize('leg', ['front', 'rear'])
@pytest.mark.parametrize('name,index', [('XZ', 1), ('YZ', 2)])
@pytest.mark.parametrize('bent', [False, True])
def test_independent_projection_preserves_document(qtbot, monkeypatch, leg, name, index, bent):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    bend = FreeArmBend((150, -30, 90) if leg == 'front' else (150, 210, 70), 20) if bent else None
    draft = FreeArmDraft((0, 0, 0), (0, 200, 160), (300, 80, 50), 10, 2,
                         bend if leg == 'front' else None, bend if leg == 'rear' else None)
    dialog = FreeArmDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, 'confirm_close', lambda: True)
    dialog._set_fields(draft)
    dialog.show()
    dialog.apply_fields()
    dialog._tabs.setCurrentWidget(dialog._cad)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    mesh, generation, form = cad._view.mesh, cad.generation, dialog._form()
    choose_projection(qtbot, monkeypatch, dialog, leg, name)
    assert dialog._tabs.currentWidget() is dialog._projections[index]
    session = dialog._projection_session
    assert session is not None and session.code == f'bend_{leg}'
    assert (session.new_vertex is None) == bent
    assert dialog.draft == draft and dialog.inner_housings is None
    assert dialog._form() == form and cad._view.mesh is mesh and cad.generation == generation
    assert not dialog._save.isEnabled()
    dialog._close_projection_session()
    assert dialog.draft == draft and dialog._save.isEnabled()
    dialog.close()


@pytest.mark.parametrize('leg', ['front', 'rear'])
@pytest.mark.parametrize('name,index', [('XZ', 1), ('YZ', 2)])
def test_snapshot_projection_selects_requested_leg(qtbot, monkeypatch, leg, name, index):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    controller, dialog = make_editor(qtbot, monkeypatch)
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    state = controller.project.to_dict()
    choose_projection(qtbot, monkeypatch, dialog, leg, name)
    assert dialog._tabs.currentWidget() is dialog._projections[index]
    assert dialog._draft is not None and dialog._draft[0] == leg
    assert not dialog._save.isEnabled() and controller.project.to_dict() == state
    assert dialog.shutdown()
    dialog.close()


@pytest.mark.parametrize('mode', ['independent', 'snapshot'])
def test_projection_action_ignores_changed_input_during_menu(qtbot, monkeypatch, mode):
    if mode == 'independent':
        dialog, draft = free_editor(qtbot, monkeypatch)
        def mutate():
            dialog._fields['front_inner_outer'].setText('51')
    else:
        pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
        controller, dialog = make_editor(qtbot, monkeypatch)
        dialog._cad._enable.setChecked(True)
        qtbot.waitUntil(lambda: dialog._cad._ready and dialog._cad._worker is None, timeout=30000)
        def mutate():
            controller.project.front.hardpoints['lbj'].x += 1
    choose_projection(qtbot, monkeypatch, dialog, 'front', 'XZ', mutate)
    if mode == 'independent':
        assert dialog._projection_session is None and dialog.draft == draft.arm
        assert dialog._tabs.currentWidget() is dialog._cad
    else:
        assert dialog._draft is None and dialog._tabs.currentIndex() == 4
        assert dialog.shutdown()
    dialog.close()


def test_independent_ambiguous_xz_leaves_draft_unchanged(qtbot, monkeypatch):
    dialog, draft = free_editor(qtbot, monkeypatch)
    mesh = dialog._cad._view.mesh
    choose_projection(qtbot, monkeypatch, dialog, 'front', 'XZ')
    assert dialog._tabs.currentWidget() is dialog._projections[1]
    assert dialog._projection_session is None and dialog.draft == draft.arm
    assert 'другую проекцию' in dialog._projection_note.text()
    assert dialog._cad._view.mesh is mesh and dialog._save.isEnabled()
    dialog.close()


@pytest.mark.parametrize('name,index', [('XZ', 1), ('YZ', 2)])
def test_snapshot_existing_bend_is_selected_not_replaced(qtbot, monkeypatch, name, index):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_editor(qtbot, monkeypatch)
    start, end = dialog.preview.anchors[0], dialog.preview.anchors[2]
    vertex = [(.5 * (start[i] + end[i])) for i in range(3)]
    vertex[2] += 50
    bends = {'front': {'vertex_mm': vertex, 'radius_mm': 20}}
    dialog._bend_editor.load(bends)
    dialog._refresh()
    cad = dialog._cad
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready and cad._worker is None, timeout=30000)
    old, mesh, generation = dialog._bend_editor.values(), cad._view.mesh, cad.generation
    choose_projection(qtbot, monkeypatch, dialog, 'front', name)
    assert dialog._tabs.currentWidget() is dialog._projections[index]
    assert dialog._point_selection.currentData() == 'bend_front' and dialog._draft is None
    assert dialog._bend_editor.values() == old and cad._view.mesh is mesh and cad.generation == generation
    assert dialog.shutdown()
    dialog.close()
