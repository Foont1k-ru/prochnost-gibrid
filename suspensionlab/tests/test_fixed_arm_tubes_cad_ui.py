"""Опциональный CAD-предпросмотр не мешает скелету и не показывает старые тела."""
import pytest
from PySide6.QtWidgets import QMessageBox

from suspensionlab.model.templates import load_template
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.fixed_arm_skeleton_dialog import FixedArmSkeletonDialog

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)


def make_dialog(qtbot, monkeypatch):
    controller = AppController()
    controller.project = load_template('ring')
    dialog = FixedArmSkeletonDialog(controller)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.show()
    dialog._capture_snapshot()
    dialog._tabs.setCurrentIndex(4)
    dialog._cad._quality.setCurrentIndex(1)
    dialog._cad._enable.setChecked(True)
    assert not dialog._reset_camera.isVisible() and not dialog._point_selection.isVisible()
    assert 'Скелет можно сохранить отдельно' in dialog._cad._status.text()
    return controller, dialog


def test_real_cad_refresh_invalid_input_and_project_change(qtbot, monkeypatch):
    controller, dialog = make_dialog(qtbot, monkeypatch)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=20000)
    assert dialog._cad._view.mesh is not None
    assert dialog._cad._view.mesh.part_names == ('tube_front', 'tube_rear')
    anchors, project = dialog.preview.anchors, controller.project.to_dict()
    dialog._radius.setValue(dialog._radius.value() + 1)
    assert dialog._cad._view.mesh is None
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=20000)
    assert dialog.preview.anchors == anchors and controller.project.to_dict() == project
    dialog._bend_editor.checks['front'].setChecked(True)
    assert dialog.preview is None and dialog._cad._view.mesh is None
    assert not dialog._save.isEnabled()
    dialog._bend_editor.checks['front'].setChecked(False)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=20000)
    point = controller.project.front.hardpoints['lbj']
    controller.move_point(point, (point.x + 1, point.y, point.z))
    assert dialog.snapshot is None and dialog._cad._view.mesh is None
    assert dialog.shutdown()
    dialog.close()


def test_stale_completion_failure_and_close_cancel(qtbot, monkeypatch):
    controller, dialog = make_dialog(qtbot, monkeypatch)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=20000)
    cad = dialog._cad
    mesh, token = cad._view.mesh, cad.generation
    controller.project.front.hardpoints['lbj'].x += 1  # even without the controller signal
    cad._completed(token, mesh)
    assert cad._view.mesh is None and not cad._ready
    assert not dialog._cad_is_current(dialog._cad_candidate)
    dialog._refresh()
    assert dialog.snapshot is None
    assert cad._view.mesh is None
    cad._completed(token, mesh)  # obsolete result cannot resurrect the old preview
    assert cad._view.mesh is None
    assert dialog.shutdown()
    dialog.close()


def test_cad_failure_does_not_block_saving_skeleton(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    _, dialog = make_dialog(qtbot, monkeypatch)
    cad = dialog._cad
    cad._timer.stop()
    cad._failed(cad.generation, 'crash')
    assert 'Скелет можно сохранить отдельно' in cad._status.text()
    assert cad._view.mesh is None and dialog._save.isEnabled()
    destination = tmp_path / 'shape.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(destination), ''))
    dialog._save_file()
    assert destination.exists()
    assert dialog.shutdown()
    dialog.close()


def test_real_bend_updates_and_shutdown_during_rebuild(qtbot, monkeypatch):
    controller, dialog = make_dialog(qtbot, monkeypatch)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=20000)
    old_mesh = dialog._cad._view.mesh
    anchors = dialog.preview.anchors
    a, b = anchors[0], anchors[2]
    vertex = [(a[0] + b[0]) / 2 + 70, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2 + 70]
    for field, value in zip(dialog._bend_editor.fields['front'], [*vertex, 20], strict=True):
        field.setText(str(value))
    dialog._bend_editor.checks['front'].setChecked(True)
    assert dialog._cad._view.mesh is None
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=20000)
    assert dialog._cad._view.mesh is not old_mesh and dialog.preview.anchors == anchors
    assert dialog._cad._document['parts'][0]['geometry']['kind'] == 'prototype_arm_bent_tube'
    before = controller.project.to_dict()
    dialog._radius.setValue(dialog._radius.value() + 1)
    qtbot.waitUntil(lambda: dialog._cad._worker is not None, timeout=5000)
    worker = dialog._cad._worker
    assert dialog.shutdown()
    assert not worker.isRunning() and dialog._cad._view.mesh is None
    assert controller.project.to_dict() == before
    dialog.close()
