"""Настоящие Qt и изолированный Open CASCADE: только в окружении с обоими пакетами."""
import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
pytest.importorskip('PySide6.QtWidgets', reason='Нужен Qt', exc_type=ImportError)

from PySide6.QtWidgets import QFileDialog  # noqa: E402

from suspensionlab.model.kim_format import write_document  # noqa: E402
from suspensionlab.model.welded_arm import make_welded_arm  # noqa: E402
from suspensionlab.ui.controller import AppController  # noqa: E402
from suspensionlab.ui.weldment_dialog import WeldmentDialog  # noqa: E402


def test_actual_cad_process_and_qt_follow_changes(qtbot, tmp_path, monkeypatch):
    c = AppController()
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 12, 2, 'required'))
    original = source.read_bytes()
    dialog = WeldmentDialog(c)
    qtbot.addWidget(dialog)
    dialog.show()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    dialog._open_file()
    dialog._start_preview()
    panel = dialog._three_d
    panel._enable.setChecked(True)
    assert panel._view.mesh is None and not dialog._save.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    old = panel._view.mesh
    assert old is not None and old.skipped_faces == old.recovered_faces == 0
    assert dialog._save.isEnabled() and not panel._view.grab().isNull()
    point = c.project.front.hardpoints['lbj']
    c.move_point(point, (point.x, point.y + 100, point.z))
    assert panel._view.mesh is None and not dialog._save.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    new = panel._view.mesh
    assert new is not None and new.triangles[:, :, 1].max() > old.triangles[:, :, 1].max() + 80
    assert dialog._save.isEnabled() and source.read_bytes() == original
    first = c.project.front.hardpoints['lca_f_in']
    c.move_point(first, point.as_tuple())
    assert panel._view.mesh is None and not dialog._save.isEnabled()
    dialog.close()


def test_editor_builds_live_3d_without_first_saving_file(qtbot, tmp_path, monkeypatch):
    import numpy as np

    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.arm_concept_dialog import ArmConceptDialog

    c = AppController()
    for code, xyz in {
        'lca_f_in': (0., 0., 0.), 'lca_r_in': (100., 0., 0.), 'lbj': (0., 100., 0.),
    }.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    before = c.project.to_dict()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    dialog.show()
    panel = dialog._three_d
    panel._enable.setChecked(True)
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    old = panel._view.mesh
    assert old is not None and dialog._save_assembly.isEnabled()
    dialog._radius.setValue(20.)
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    new = panel._view.mesh
    assert new is not None and np.ptp(new.triangles[:, :, 2]) > np.ptp(old.triangles[:, :, 2]) + 10
    assert c.project.to_dict() == before and not c.dirty and list(tmp_path.iterdir()) == []
    point = c.project.front.hardpoints['lbj']
    c.move_point(point, (point.x, point.y + 100, point.z))
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    qtbot.waitUntil(lambda: panel._view.mesh is not None, timeout=45000)
    target = tmp_path / 'result.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    dialog._save_weldment_snapshot()
    doc = read_document(target, 'assembly')
    assert doc['parts'][0]['geometry']['radius_mm'] == 20
    assert doc['parts'][0]['geometry']['source']['coordinates_mm'][2][1] == 200
    dialog._wall.setValue(20.)
    assert panel._view.mesh is None and not dialog._save_assembly.isEnabled()
    dialog.close()


def test_bent_tube_editor_and_reopened_assembly_use_actual_cad(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.arm_concept_dialog import ArmConceptDialog

    c = AppController()
    for code, xyz in {
        'lca_f_in': (0., 0., 0.), 'lca_r_in': (0., -100., 0.), 'lbj': (100., 100., 0.),
    }.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = ArmConceptDialog(c)
    qtbot.addWidget(d)
    d.show()
    for field, value in zip(d._bend_fields['front'], ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    d._bend_checks['front'].setChecked(True)
    d._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    old = d._three_d._view.mesh
    assert old is not None and d._save_assembly.isEnabled()
    path = tmp_path / 'bent.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_weldment_snapshot()
    doc = read_document(path, 'assembly')
    assert doc['version'] == '0.3' and doc['parts'][0]['geometry']['bend_radius_mm'] == 20
    viewer = WeldmentDialog(c)
    qtbot.addWidget(viewer)
    viewer.show()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    viewer._open_file()
    viewer._start_preview()
    viewer._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: viewer._three_d._view.mesh is not None, timeout=45000)
    outer = c.project.front.hardpoints['lbj']
    c.move_point(outer, (100, 150, 0))
    assert d._three_d._view.mesh is None and viewer._three_d._view.mesh is None
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None and viewer._three_d._view.mesh is not None,
                    timeout=45000)
    assert d._three_d._view.mesh.triangles[:, :, 1].max() > old.triangles[:, :, 1].max() + 40
    c.move_point(outer, (100, 10, 0))
    assert d._three_d._view.mesh is None and viewer._three_d._view.mesh is None
    assert not d._save_assembly.isEnabled() and not viewer._save.isEnabled()
    d.close()
    viewer.close()


def test_reopened_bend_edits_rebuild_real_cad_and_clear_invalid(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    c = AppController()
    for code, xyz in {'lca_f_in': (0., 0., 0.), 'lca_r_in': (0., -100., 0.), 'lbj': (100., 100., 0.)}.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 10, 2, 'unknown', bends={
        'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
    }))
    original = source.read_bytes()
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    d.show()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    d._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    d._bend_editor.fields['front'][3].setText('25')
    assert d._three_d._view.mesh is None and not d._save.isEnabled()
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    assert d._save.isEnabled()
    d._bend_editor.fields['front'][3].setText('1000')
    assert d._three_d._view.mesh is None and d._canvas.concept is None and not d._save.isEnabled()
    d._bend_editor.fields['front'][3].setText('25')
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    target = tmp_path / 'copy.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    from suspensionlab.model.kim_format import read_document
    assert read_document(target, 'assembly')['parts'][0]['geometry']['bend_radius_mm'] == 25
    assert source.read_bytes() == original
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d.close()


def test_rear_tube_editor_builds_and_rebuilds_real_cad(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.rear_tube_dialog import RearTubeDialog

    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    for code, xyz in {'ll_in_l': (0., 0., 0.), 'll_out_l': (100., 100., 0.)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d.show()
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    assert d._save.isEnabled()
    d._bend.setChecked(True)
    assert d._three_d._view.mesh is None and not d._save.isEnabled()
    for field, value in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    assert d._save.isEnabled()
    d._fields[3].setText('1000')
    assert d._three_d._view.mesh is None and not d._save.isEnabled()
    d._fields[3].setText('20')
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    target = tmp_path / 'rear.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    assert read_document(target, 'assembly')['bend']['radius_mm'] == 20
    d.close()


def test_reopened_rear_tube_uses_saved_3d_then_updates_current_cad(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.model.rear_tube import make_rear_tube
    from suspensionlab.ui.rear_tube_dialog import RearTubeDialog

    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    for code, xyz in {'ll_in_l': (0., 0., 0.), 'll_out_l': (100., 100., 0.)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    source = tmp_path / 'rear.kima'
    document = make_rear_tube(c.project, 'rear_lower_left', 10, 2,
                              {'vertex_mm': [100, 0, 0], 'radius_mm': 20})
    write_document(source, 'assembly', document)
    original = source.read_bytes()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d.show()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    assert not d._save.isEnabled() and d._candidate == document
    d._start_preview()
    assert d._three_d._view.mesh is None and not d._save.isEnabled()
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    d._fields[3].setText('25')
    assert d._three_d._view.mesh is None and not d._save.isEnabled()
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    assert d._save.isEnabled()
    target = tmp_path / 'rear-copy.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    assert read_document(target, 'assembly')['bend']['radius_mm'] == 25 and source.read_bytes() == original
    d.close()


def test_front_right_reopened_tubes_rebuild_real_cad(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.front_tube_arm import make_front_tube_arm
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.front_tubes_dialog import FrontTubesDialog

    c = AppController()
    for code, xyz in {'uca_f_in': (0., 0., 0.), 'uca_r_in': (0., -100., 0.), 'ubj': (100., 100., 0.)}.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    bends = {'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
             'rear': {'vertex_mm': [100, 100, 0], 'radius_mm': 25}}
    source = tmp_path / 'front-right.kima'
    doc = make_front_tube_arm(c.project, 'front_upper_right', 10, 2, bends)
    write_document(source, 'assembly', doc)
    original = source.read_bytes()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d.show()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    assert not d._save.isEnabled() and d._candidate == doc
    d._start_preview()
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    d._bend_editor.fields['rear'][3].setText('30')
    assert d._three_d._view.mesh is None and not d._save.isEnabled()
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    d._bend_editor.fields['rear'][3].setText('1000')
    assert d._three_d._view.mesh is None and not d._save.isEnabled()
    d._bend_editor.fields['rear'][3].setText('30')
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    target = tmp_path / 'copy.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    assert read_document(target, 'assembly')['bends']['rear']['radius_mm'] == 30
    assert source.read_bytes() == original
    d.close()


def test_rear_pair_rebuilds_real_cad_before_save(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.rear_tube_dialog import RearTubeDialog

    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    for code, xyz in {'ll_in_l': (0, 0, 0), 'll_out_l': (100, 100, 0),
                      'll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d.show()
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._bend.setChecked(True)
    for field, value in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    d._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    d._pair.click()
    assert d._arm.currentData() == 'rear_lower_right'
    assert d._three_d._view.mesh is None and not d._save.isEnabled()
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None and d._save.isEnabled(), timeout=45000)
    path = tmp_path / 'pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_copy()
    assert read_document(path, 'assembly')['arm'] == 'rear_lower_right'
    d._pair_baseline = d._pair_state()
    d.close()


def test_rear_live_pair_3d_invalidates_and_rebuilds_on_edits(qtbot):
    from suspensionlab.ui.rear_tube_dialog import RearTubeDialog

    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    for code, xyz in {'ll_in_l': (0, 0, 0), 'll_out_l': (100, 100, 0),
                      'll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._bend.setChecked(True)
    for field, value in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    d._pair_three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._pair_three_d._view.mesh is not None, timeout=45000)
    old = d._pair_three_d._view.mesh
    d._fields[3].setText('30')
    assert d._pair_three_d._view.mesh is None
    qtbot.waitUntil(lambda: d._pair_three_d._view.mesh is not None, timeout=45000)
    assert d._pair_three_d._view.mesh is not old
    d._pair_roll.setText('invalid')
    assert d._pair_three_d._view.mesh is None and d._pair_three_d._document is None
    d._baseline, d._saved_candidate = d._input_state(), None
    d._pair_baseline = d._pair_state()
    assert d.shutdown()
    d.close()


def test_saved_rear_pair_reopens_and_rebuilds_both_cad_views(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.rear_tube_dialog import RearTubeDialog

    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    for code, xyz in {'ll_in_l': (0, 0, 0), 'll_out_l': (100, 100, 0),
                      'll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._bend.setChecked(True)
    for field, text in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(text)
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    d._three_d._enable.setChecked(True)
    d._pair_three_d._enable.setChecked(True)
    d._pair_assembly_3d._enable.setChecked(True)
    assert not d._save_pair.isEnabled()
    qtbot.waitUntil(lambda: d._save_pair.isEnabled(), timeout=45000)
    assert d._three_d._view.mesh is not None and d._pair_three_d._view.mesh is not None
    assert d._pair_assembly_3d._view.mesh is not None
    path = tmp_path / 'paired.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_pair_copy()
    assert read_document(path, 'assembly')['version'] == '0.6'
    assert d.shutdown()
    d.close()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    d._three_d._enable.setChecked(True)
    d._pair_three_d._enable.setChecked(True)
    d._pair_assembly_3d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None and d._pair_three_d._view.mesh is not None and
                    d._pair_assembly_3d._view.mesh is not None,
                    timeout=45000)
    d._start_preview()
    qtbot.waitUntil(lambda: d._save_pair.isEnabled(), timeout=45000)
    d._fields[3].setText('30')
    assert d._pair_assembly_3d._view.mesh is None and not d._save_pair.isEnabled()
    qtbot.waitUntil(lambda: d._save_pair.isEnabled(), timeout=45000)
    target = tmp_path / 'paired-edit.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_pair_copy()
    assert read_document(target, 'assembly')['source']['bend']['radius_mm'] == 30
    assert d.shutdown()
    d.close()


def test_front_mirrored_pair_3d_and_persistent_reopen(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.front_pair_snapshot import front_pair_sides
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.front_tubes_dialog import FrontTubesDialog

    c = AppController()
    for code, xyz in {'uca_f_in': (0, 20, 0), 'uca_r_in': (0, -80, 0), 'ubj': (100, 120, 0)}.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    for leg, values in [('front', ('100', '20', '0', '20')), ('rear', ('100', '-80', '0', '25'))]:
        d._bend_editor.checks[leg].setChecked(True)
        for field, value in zip(d._bend_editor.fields[leg], values, strict=True):
            field.setText(value)
    d._pair_3d._enable.setChecked(True)
    assert not d._save_pair.isEnabled()
    qtbot.waitUntil(lambda: d._save_pair.isEnabled(), timeout=45000)
    assert d._pair_3d._view.mesh is not None
    path = tmp_path / 'front-pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_pair_copy()
    assert read_document(path, 'assembly')['version'] == '0.7'
    assert d.shutdown()
    d.close()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    d._pair_3d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._pair_3d._view.mesh is not None, timeout=45000)
    d._start_preview()
    qtbot.waitUntil(lambda: d._save_pair.isEnabled(), timeout=45000)
    d._bend_editor.fields['rear'][3].setText('30')
    assert d._pair_3d._view.mesh is None and not d._save_pair.isEnabled()
    qtbot.waitUntil(lambda: d._save_pair.isEnabled(), timeout=45000)
    target = tmp_path / 'front-pair-edit.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_pair_copy()
    assert front_pair_sides(read_document(target, 'assembly'))[1]['bends']['rear']['radius_mm'] == 30
    assert d.shutdown()
    d.close()


def test_joint_editor_3d_rebuild_save_and_open(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.joint_concept_dialog import JointConceptDialog

    c = AppController()
    d = JointConceptDialog(c)
    qtbot.addWidget(d)
    d._three_d._enable.setChecked(True)
    assert not d._save.isEnabled()
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None and d._save.isEnabled(), timeout=45000)
    d._fields['ball']['outer_radius_mm'].setText('23')
    assert d._three_d._view.mesh is None and not d._save.isEnabled()
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None and d._save.isEnabled(), timeout=45000)
    path = tmp_path / 'joint.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_copy()
    assert read_document(path, 'assembly')['version'] == '0.8'
    assert d.shutdown()
    d.close()
    d = JointConceptDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    d._three_d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._three_d._view.mesh is not None, timeout=45000)
    assert d._candidate['parameters']['outer_radius_mm'] == 23
    assert d.shutdown()
    d.close()


def test_front_layout_embedded_joints_real_3d_and_copy(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.front_tubes_dialog import FrontTubesDialog

    c = AppController()
    paths = {}
    for kind in ('ball', 'bushing'):
        paths[kind] = tmp_path / f'{kind}.kima'
        write_document(paths[kind], 'assembly', make_joint_concept(kind, DEFAULTS[kind]))
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    for kind in ('ball', 'bushing'):
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args, k=kind: (str(paths[k]), ''))
        d._load_joint(kind)
    d._layout_3d._enable.setChecked(True)
    assert not d._save_layout.isEnabled()
    qtbot.waitUntil(lambda: d._layout_3d._view.mesh is not None and d._save_layout.isEnabled(), timeout=45000)
    d._radius.setText('13')
    assert d._layout_3d._view.mesh is None and not d._save_layout.isEnabled()
    qtbot.waitUntil(lambda: d._layout_3d._view.mesh is not None and d._save_layout.isEnabled(), timeout=45000)
    d._bushing_axis.setCurrentIndex(d._bushing_axis.findData('z'))
    assert d._layout_3d._view.mesh is None and not d._save_layout.isEnabled()
    qtbot.waitUntil(lambda: d._layout_3d._view.mesh is not None and d._save_layout.isEnabled(), timeout=45000)
    path = tmp_path / 'layout.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_layout_copy()
    saved = read_document(path, 'assembly')
    assert saved['version'] == '0.13' and saved['axis'] == 'z'
    assert d.shutdown()
    d.close()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    assert d._bushing_axis.currentData() == 'z'
    d._layout_3d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._layout_3d._view.mesh is not None, timeout=45000)
    assert not d._save_layout.isEnabled()
    d._start_preview()
    qtbot.waitUntil(lambda: d._save_layout.isEnabled(), timeout=45000)
    assert d.shutdown()
    d.close()


def test_rear_layout_real_3d_rebuild_and_reopen(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.rear_tube_dialog import RearTubeDialog

    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    for code, xyz in {'ll_in_l': (0, 0, 0), 'll_out_l': (100, 100, 0),
                      'll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
        p = c.project.rear.hardpoints[code]
        p.x, p.y, p.z = xyz
    bush = tmp_path / 'bush.kima'
    write_document(bush, 'assembly', make_joint_concept('bushing', DEFAULTS['bushing']))
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(bush), ''))
    d._load_joint()
    d._layout_3d._enable.setChecked(True)
    assert not d._save_layout.isEnabled()
    qtbot.waitUntil(lambda: d._layout_3d._view.mesh is not None and d._save_layout.isEnabled(), timeout=45000)
    d._joint_axis.setCurrentIndex(d._joint_axis.findData('z'))
    assert d._layout_3d._view.mesh is None and not d._save_layout.isEnabled()
    qtbot.waitUntil(lambda: d._layout_3d._view.mesh is not None and d._save_layout.isEnabled(), timeout=45000)
    path = tmp_path / 'rear-layout.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_layout_copy()
    assert read_document(path, 'assembly')['axis'] == 'z'
    assert d.shutdown()
    d.close()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    d._layout_3d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._layout_3d._view.mesh is not None, timeout=45000)
    assert not d._save_layout.isEnabled() and d._joint_axis.currentData() == 'z'
    d._start_preview()
    qtbot.waitUntil(lambda: d._save_layout.isEnabled(), timeout=45000)
    assert d.shutdown()
    d.close()


def test_same_front_pair_real_3d_rebuild_and_reopen(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.front_tubes_dialog import FrontTubesDialog

    c = AppController()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (0, -100, 0), 'ubj': (100, 100, 0)}.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    d._pair_3d._enable.setChecked(True)
    assert not d._save_pair.isEnabled()
    qtbot.waitUntil(lambda: d._pair_3d._view.mesh is not None and d._save_pair.isEnabled(), timeout=45000)
    target = tmp_path / 'same.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_pair_copy()
    assert read_document(target, 'assembly')['version'] == '0.11'
    assert d.shutdown()
    d.close()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(target), ''))
    d._open_file()
    d._pair_3d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._pair_3d._view.mesh is not None, timeout=45000)
    assert not d._save_pair.isEnabled() and d._pair_mode.currentData() == 'same'
    d._start_preview()
    qtbot.waitUntil(lambda: d._save_pair.isEnabled(), timeout=45000)
    assert d.shutdown()
    d.close()


def test_front_same_layout_3d_save_and_reopen(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept
    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.front_tubes_dialog import FrontTubesDialog

    c = AppController()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (0, -100, 0), 'ubj': (100, 100, 0)}.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    for kind in ('ball', 'bushing'):
        path = tmp_path / f'{kind}.kima'
        write_document(path, 'assembly', make_joint_concept(kind, DEFAULTS[kind]))
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args, path=path: (str(path), ''))
        d._load_joint(kind)
    d._layout_3d._enable.setChecked(True)
    assert not d._save_layout.isEnabled()
    qtbot.waitUntil(lambda: d._layout_3d._view.mesh is not None and d._save_layout.isEnabled(), timeout=45000)
    target = tmp_path / 'same-layout.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_layout_copy()
    saved = read_document(target, 'assembly')
    assert saved['version'] == '0.14' and saved['axis'] == 'x'
    assert d.shutdown()
    d.close()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(target), ''))
    d._open_file()
    d._layout_3d._enable.setChecked(True)
    qtbot.waitUntil(lambda: d._layout_3d._view.mesh is not None, timeout=45000)
    assert not d._save_layout.isEnabled() and d._pair_mode.currentData() == 'same'
    d._start_preview()
    qtbot.waitUntil(lambda: d._save_layout.isEnabled(), timeout=45000)
    assert d.shutdown()
    d.close()


def test_quality_selection_real_cad_rebuilds_preview(qtbot):
    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept
    from suspensionlab.ui.weldment_3d import Weldment3D

    doc = make_joint_concept('bushing', DEFAULTS['bushing'])
    panel = Weldment3D(joint=True)
    qtbot.addWidget(panel)
    panel.set_document(doc)
    panel._quality.setCurrentIndex(1)
    panel._enable.setChecked(True)
    qtbot.waitUntil(lambda: panel._view.mesh is not None and panel.can_save(), timeout=45000)
    coarse_count = len(panel._view.mesh.triangles)
    panel._quality.setCurrentIndex(0)
    assert panel._view.mesh is None and not panel.can_save()
    qtbot.waitUntil(lambda: panel._view.mesh is not None and panel.can_save(), timeout=45000)
    assert len(panel._view.mesh.triangles) > coarse_count
    assert panel._document == doc and panel.shutdown()
    panel.close()
