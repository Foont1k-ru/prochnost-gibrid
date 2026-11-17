"""Пользовательские изгибы, без угадывания и без подмены прямыми трубами."""
from PySide6.QtWidgets import QFileDialog

from suspensionlab.model.kim_format import read_document
from suspensionlab.ui.arm_concept_dialog import ArmConceptDialog
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.weldment_dialog import WeldmentDialog


def controller():
    c = AppController()
    for code, xyz in {'lca_f_in': (0., 0., 0.), 'lca_r_in': (0., -100., 0.), 'lbj': (100., 100., 0.)}.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    return c


def test_explicit_bend_inputs_show_curved_2d_save_and_reopen(qtbot, tmp_path, monkeypatch):
    c = controller()
    before = c.project.to_dict()
    d = ArmConceptDialog(c)
    qtbot.addWidget(d)
    d._bend_checks['front'].setChecked(True)
    assert d._candidate is None and d._canvas.concept is None
    assert not d._save_assembly.isEnabled() and not d._save_tube.isEnabled()
    for field, value in zip(d._bend_fields['front'], ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    assert d._candidate is not None and d._candidate['version'] == '0.3'
    assert d._canvas.paths is not None and len(d._canvas.paths[0]) > 3
    assert d._save_assembly.isEnabled() and not d._save_tube.isEnabled()
    assert c.project.to_dict() == before and not c.dirty
    path = tmp_path / 'bent.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_weldment_snapshot()
    saved = read_document(path, 'assembly')
    assert saved['parts'][0]['geometry']['bend_vertex_mm'] == [100, 0, 0]
    assert saved['parts'][0]['geometry']['bend_radius_mm'] == 20
    viewer = WeldmentDialog(c)
    qtbot.addWidget(viewer)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    viewer._open_file()
    viewer._start_preview()
    assert viewer._candidate is not None and viewer._candidate['version'] == '0.3'
    assert viewer._canvas.paths is not None and len(viewer._canvas.paths[0]) > 3
    original = path.read_bytes()
    outer = c.project.front.hardpoints['lbj']
    c.move_point(outer, (100, 10, 0))  # radius no longer fits
    assert d._candidate is None and d._canvas.concept is None
    assert viewer._candidate is None and viewer._canvas.concept is None
    assert not d._save_assembly.isEnabled() and not viewer._save.isEnabled()
    assert path.read_bytes() == original
    assert d.shutdown() and viewer.shutdown()


def test_bend_can_be_removed_without_silently_changing_stored_snapshot(qtbot):
    c = controller()
    d = ArmConceptDialog(c)
    qtbot.addWidget(d)
    for field, value in zip(d._bend_fields['rear'], ('100', '-100', '0', '25'), strict=True):
        field.setText(value)
    d._bend_checks['rear'].setChecked(True)
    assert d._candidate is not None and d._candidate['version'] == '0.3'
    assert d._candidate['parts'][1]['geometry']['kind'] == 'prototype_arm_bent_tube'
    assert not d._save_tube.isEnabled()
    d._bend_checks['rear'].setChecked(False)
    assert d._candidate is not None and d._candidate['version'] == '0.2'
    assert d._save_tube.isEnabled()
    d._style.setCurrentIndex(1)
    assert not d._bend_checks['rear'].isEnabled() and d._three_d._document is None
    assert d.shutdown()
