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
