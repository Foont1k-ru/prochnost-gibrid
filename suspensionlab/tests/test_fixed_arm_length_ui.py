import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox
from test_fixed_arm_tube_joint_ui import make_editor

from suspensionlab.model.bent_tube import make_bend_path


def setup_bend(dialog):
    a, b = dialog.preview.anchors[0], dialog.preview.anchors[2]
    vertex = [(a[i] + b[i]) / 2 for i in range(3)]
    vertex[2] += 50
    dialog._bend_editor.load({'front': {'vertex_mm': vertex, 'radius_mm': 20}})
    dialog._bend_editor.changed.emit()
    return a, b


def test_length_updates_bend_not_supports_and_rejects_bad_input(qtbot, monkeypatch):
    _, dialog = make_editor(qtbot, monkeypatch)
    a, b = setup_bend(dialog)
    initial = dialog._bend_editor.values()['front']
    current = make_bend_path(a, initial['vertex_mm'], b, 20, dialog._radius.value()).length
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (current + 10, True))
    dialog._edit_tube_length('front')
    assert not warnings, warnings
    changed = dialog._bend_editor.values()['front']
    assert make_bend_path(a, changed['vertex_mm'], b, 20, dialog._radius.value()).length == pytest.approx(current + 10)
    assert dialog.preview.anchors[0] == a and dialog.preview.anchors[2] == b
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (1, True))
    dialog._edit_tube_length('front')
    assert dialog._bend_editor.values()['front'] == changed
    assert dialog.shutdown()
    dialog.close()


def test_length_cancel_or_stale_project_does_not_mutate(qtbot, monkeypatch):
    controller, dialog = make_editor(qtbot, monkeypatch)
    setup_bend(dialog)
    original = dialog._bend_editor.values()
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (300, False))
    dialog._edit_tube_length('front')
    assert dialog._bend_editor.values() == original
    def stale(*args):
        controller.project.front.hardpoints['lbj'].x += 1
        return 300, True
    monkeypatch.setattr(QInputDialog, 'getDouble', stale)
    dialog._edit_tube_length('front')
    assert dialog._bend_editor.values() == original
    assert dialog.shutdown()
    dialog.close()


def test_straight_tube_requires_explicit_direction(qtbot, monkeypatch):
    _, dialog = make_editor(qtbot, monkeypatch)
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: messages.append(args[2]))
    dialog._edit_tube_length('front')
    assert 'направление изгиба' in messages[0].lower()
    assert not dialog._bend_editor.values()
    assert dialog.shutdown()
    dialog.close()


def test_length_edit_accepts_valid_bend_beyond_invalid_intermediate(qtbot, monkeypatch):
    import math

    _, dialog = make_editor(qtbot, monkeypatch)
    start, end = dialog.preview.anchors[0], dialog.preview.anchors[2]
    chord = math.dist(start, end)
    axis = tuple((end[i] - start[i]) / chord for i in range(3))
    perpendicular_norm = math.hypot(axis[0], axis[1])
    perpendicular = (-axis[1] / perpendicular_norm, axis[0] / perpendicular_norm, 0.)
    along = 52.17366213524382 / 56.3662398598089 * chord
    initial = 1.3394635386219251 / 56.3662398598089 * chord
    target_height = 30.111284658939333 / 56.3662398598089 * chord
    radius = 16.995141324006216 / 56.3662398598089 * chord
    def vertex(height):
        return [start[i] + along * axis[i] + height * perpendicular[i] for i in range(3)]
    dialog._bend_editor.load({'front': {'vertex_mm': vertex(initial), 'radius_mm': radius}})
    dialog._bend_editor.changed.emit()
    assert dialog.preview is not None and dialog._cad_candidate is not None
    requested = make_bend_path(start, vertex(target_height), end, radius, dialog._radius.value()).length
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (requested, True))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    dialog._edit_tube_length('front')
    assert not warnings
    changed = dialog._bend_editor.values()['front']
    assert changed['vertex_mm'] == pytest.approx(vertex(target_height), abs=1e-5)
    assert make_bend_path(start, changed['vertex_mm'], end, radius, dialog._radius.value()).length == pytest.approx(requested)
    assert dialog.preview.anchors[0] == start and dialog.preview.anchors[2] == end
    assert dialog.shutdown()
    dialog.close()


def test_cad_context_menu_can_edit_length(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    import numpy as np
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    _, dialog = make_editor(qtbot, monkeypatch)
    a, b = setup_bend(dialog)
    old = dialog._bend_editor.values()['front']
    length = make_bend_path(a, old['vertex_mm'], b, old['radius_mm'], dialog._radius.value()).length
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    index = int(np.flatnonzero(cad._view.mesh.triangle_parts == 0)[0])
    cad._view.triangle_picked.emit(index)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (length + 3., True))
    def choose_length():
        menu = QApplication.activePopupWidget()
        if not isinstance(menu, QMenu):
            return
        qtbot.keyClick(menu, Qt.Key.Key_Down)
        qtbot.keyClick(menu, Qt.Key.Key_Right)
        submenu = QApplication.activePopupWidget()
        if not isinstance(submenu, QMenu) or submenu is menu:
            menu.close()
            return
        action = next(action for action in submenu.actions() if action.text().startswith('Длину трубы'))
        qtbot.mouseClick(submenu, Qt.MouseButton.LeftButton, pos=submenu.actionGeometry(action).center())
    QTimer.singleShot(50, choose_length)
    qtbot.mouseClick(cad._view, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    result = dialog._bend_editor.values()['front']
    assert make_bend_path(a, result['vertex_mm'], b, result['radius_mm'], dialog._radius.value()).length == pytest.approx(length + 3.)
    assert dialog.shutdown()
    dialog.close()
