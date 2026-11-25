"""Центральный корпус: интерфейс, изоляция снимка и сохранение рецепта."""
import json
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
from test_fixed_arm_tube_joint_ui import make_editor

from suspensionlab.model import fixed_arm_skeleton_io as io
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm
from suspensionlab.model.templates import load_template
from suspensionlab.ui.ball_housing_dialog import BallHousingDialog


def parameters():
    return {'outer_diameter_mm': 120., 'bore_diameter_mm': 30., 'length_mm': 200.,
            'axis': [0., 0., 1.], 'offset_mm': [10., -30., 12.]}


def test_file_roundtrip_and_strict_rejection(tmp_path):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, 0, 0)
    before = deepcopy(project.to_dict())
    path = tmp_path / 'ball.slarm'
    io.write_skeleton(path, snapshot, project, 10, 2, {}, ball_housing=parameters())
    source = json.loads(path.read_text(encoding='utf-8'))
    assert source['version'] == '7'
    loaded = io.read_skeleton(path, project)
    assert loaded.ball_housing == parameters() and loaded.tube_joint is None
    assert loaded.snapshot == snapshot and project.to_dict() == before
    cases = [
        lambda doc: doc['geometry']['ball_housing'].update(axis=[0, 0, 0]),
        lambda doc: doc['geometry']['ball_housing'].update(bore_diameter_mm=120),
        lambda doc: doc['geometry'].update(tube_joint={'target': 'front', 'radial_clearance_mm': 0}),
        lambda doc: doc['geometry'].update(clearance_requirements_mm={'tube_front|tube_rear': 1}),
        lambda doc: doc['geometry'].update(extra=0),
    ]
    for index, mutate in enumerate(cases):
        changed = deepcopy(source)
        mutate(changed)
        bad = tmp_path / f'bad-{index}.slarm'
        bad.write_text(json.dumps(changed), encoding='utf-8')
        with pytest.raises(io.SkeletonFileError):
            io.read_skeleton(bad, project)
    project.front.hardpoints['lbj'].x += .000001
    with pytest.raises(io.SkeletonFileError):
        io.read_skeleton(path, project)


def test_dialog_input_and_validation(qtbot):
    dialog = BallHousingDialog()
    qtbot.addWidget(dialog)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    for key, value in (('outer_diameter_mm', '120'), ('bore_diameter_mm', '30'), ('length_mm', '200'),
                       ('offset_x', '10'), ('offset_y', '-30'), ('offset_z', '12')):
        dialog.fields[key].setText(value)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.result_values == parameters()


def test_edit_save_open_and_disable_incompatible_joint(qtbot, monkeypatch, tmp_path):
    controller, dialog = make_editor(qtbot, monkeypatch)
    dialog._tube_joint.setCurrentIndex(dialog._tube_joint.findData('miter'))
    old = dialog._cad_candidate
    def edit(modal):
        modal.result_values = parameters()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BallHousingDialog, 'exec', edit)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    dialog._edit_ball_housing()
    assert dialog._ball_housing is None and dialog._tube_joint.currentData() == 'miter'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog._edit_ball_housing()
    assert dialog._ball_housing == parameters() and dialog._tube_joint.currentData() is None
    assert not dialog._tube_joint.isEnabled() and dialog._cad_candidate['version'] == '5'
    assert not dialog._cad_is_current(old) and dialog._cad_is_current(dialog._cad_candidate)
    ball = dialog.preview.anchors[2]
    center = tuple(ball[i] + parameters()['offset_mm'][i] for i in range(3))
    assert dialog.preview.centerlines[0][-1] == pytest.approx(center)
    assert dialog.preview.centerlines[1][-1] == pytest.approx(center)
    assert dialog._point_selection.findData('ball_housing_center') >= 0
    assert dialog._overlap._document is None
    path = tmp_path / 'skeleton.slarm'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._save_file()
    assert json.loads(path.read_text(encoding='utf-8'))['version'] == '7'
    dialog._remove_ball_housing()
    assert dialog._ball_housing is None and dialog._tube_joint.isEnabled()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    dialog._open_file()
    assert dialog._ball_housing == parameters() and dialog._cad_candidate['version'] == '5'
    assert dialog.preview.anchors[2] == ball and dialog.preview.centerlines[0][-1] == pytest.approx(center)
    assert dialog.confirm_close()
    controller.project.front.hardpoints['lbj'].x += 1
    dialog._refresh()
    assert dialog._ball_housing is None and dialog._cad_candidate is None
    assert dialog.shutdown()
    dialog.close()


def test_real_cad_rebuild_and_invalid_candidate_clears_mesh(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_editor(qtbot, monkeypatch)
    def edit(modal):
        modal.result_values = parameters()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BallHousingDialog, 'exec', edit)
    dialog._edit_ball_housing()
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    assert cad._view.mesh.part_names == ('tube_front', 'tube_rear', 'ball_housing')
    assert 'подрезаны по отдельному центральному корпусу' in cad._status.text()
    def invalid(modal):
        modal.result_values = {**parameters(), 'outer_diameter_mm': 60.}
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BallHousingDialog, 'exec', invalid)
    dialog._edit_ball_housing()
    assert cad._view.mesh is None
    qtbot.waitUntil(lambda: not cad._ready and 'не построены' in cad._status.text(), timeout=30000)
    assert cad._view.mesh is None
    assert dialog.shutdown()
    dialog.close()


def test_dialog_cancellation_or_changed_project_never_accepts_result(qtbot, monkeypatch):
    controller, dialog = make_editor(qtbot, monkeypatch)
    original = dialog._cad_candidate
    monkeypatch.setattr(BallHousingDialog, 'exec', lambda modal: QDialog.DialogCode.Rejected)
    dialog._edit_ball_housing()
    assert dialog._ball_housing is None and dialog._cad_candidate == original
    def change_during_edit(modal):
        modal.result_values = parameters()
        controller.project.front.hardpoints['lbj'].x += 1
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BallHousingDialog, 'exec', change_during_edit)
    dialog._edit_ball_housing()
    assert dialog._ball_housing is None and dialog.snapshot is None and dialog._cad_candidate is None
    assert dialog.shutdown()
    dialog.close()


def test_invalid_axes_or_bend_do_not_replace_previous_central_housing(qtbot, monkeypatch):
    _, dialog = make_editor(qtbot, monkeypatch)
    def edit(modal):
        modal.result_values = parameters()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BallHousingDialog, 'exec', edit)
    dialog._edit_ball_housing()
    before = dialog._state(), dialog.preview, dialog._cad_candidate
    def bad(modal):
        modal.result_values = {**parameters(), 'axis': [0, 0, 0]}
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BallHousingDialog, 'exec', bad)
    dialog._edit_ball_housing()
    assert (dialog._state(), dialog.preview, dialog._cad_candidate) == before
    assert 'не принят' in dialog._ball_status.text()
    assert dialog.shutdown()
    dialog.close()


def test_bent_centerline_and_cad_follow_offset_not_ball(qtbot, monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    _, dialog = make_editor(qtbot, monkeypatch)
    def edit(modal):
        modal.result_values = parameters()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BallHousingDialog, 'exec', edit)
    dialog._edit_ball_housing()
    start, end = dialog.preview.centerlines[0][0], dialog.preview.centerlines[0][-1]
    vertex = [(start[i] + end[i]) / 2 for i in range(3)]
    vertex[2] += 50
    for field, value in zip(dialog._bend_editor.fields['front'], [*vertex, 20], strict=True):
        field.setText(str(value))
    dialog._bend_editor.checks['front'].setChecked(True)
    assert len(dialog.preview.centerlines[0]) > 2
    assert dialog.preview.centerlines[0][-1] == pytest.approx(end)
    cad = dialog._cad
    cad._quality.setCurrentIndex(1)
    cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: cad._ready, timeout=30000)
    assert cad._view.mesh.part_names == ('tube_front', 'tube_rear', 'ball_housing')
    assert dialog.shutdown()
    dialog.close()
