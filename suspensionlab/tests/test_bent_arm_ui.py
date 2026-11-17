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


def test_saved_bends_can_be_edited_without_modifying_source_or_project(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import write_document
    from suspensionlab.model.welded_arm import make_welded_arm

    c = controller()
    doc = make_welded_arm(c.project, 10, 2, 'required', bends={
        'front': {'vertex_mm': [100.12345678901234, 0, 0], 'radius_mm': 20},
    })
    doc['name'] = 'Мой рычаг'
    doc['parts'][0]['name'] = 'Моя труба'
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', doc)
    source_bytes, before = source.read_bytes(), c.project.to_dict()
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    editor = d._bend_editor
    assert not editor.checks['front'].isEnabled()
    assert editor.values()['front']['vertex_mm'][0] == 100.12345678901234
    d._start_preview()
    assert editor.checks['front'].isEnabled() and d._candidate is not None
    old_paths = d._canvas.paths
    editor.fields['front'][3].setText('25')
    assert d._candidate is not None and d._canvas.paths != old_paths
    assert d._edit_status.text() and d._save.isEnabled()
    target = tmp_path / 'new.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    new = read_document(target, 'assembly')
    assert new['parts'][0]['geometry']['bend_radius_mm'] == 25
    assert new['parts'][0]['geometry']['bend_vertex_mm'][0] == 100.12345678901234
    assert new['name'] == 'Мой рычаг' and new['parts'][0]['name'] == 'Моя труба'
    assert source.read_bytes() == source_bytes and c.project.to_dict() == before and not c.dirty
    assert not d._edit_status.text() and d.confirm_close()
    assert d.shutdown()


def test_add_remove_and_invalid_saved_bends_never_show_wrong_geometry(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.kim_format import write_document
    from suspensionlab.model.welded_arm import make_welded_arm

    c = controller()
    source = tmp_path / 'straight.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 10, 2, 'unknown'))
    before = source.read_bytes()
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    editor = d._bend_editor
    editor.checks['front'].setChecked(True)
    assert d._canvas.concept is None and d._candidate is None and not d._save.isEnabled()
    for field, value in zip(editor.fields['front'], ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    assert d._candidate is not None and d._candidate['version'] == '0.3'
    editor.fields['front'][3].setText('1000')
    assert d._candidate is None and d._canvas.concept is None and not d._save.isEnabled()
    editor.fields['front'][3].setText('20')
    assert d._candidate is not None
    editor.checks['front'].setChecked(False)
    assert d._candidate is not None and d._candidate['version'] == '0.2'
    assert source.read_bytes() == before and d.confirm_close()  # no effective change
    assert d.shutdown()


def test_unsaved_bends_prompt_before_open_and_close(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from suspensionlab.model.kim_format import write_document
    from suspensionlab.model.welded_arm import make_welded_arm

    c = controller()
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
    d._bend_editor.fields['front'][3].setText('25')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(tmp_path / 'other.kima'), ''))
    d._open_file()
    assert d._source is not None and d._bend_editor.fields['front'][3].text() == '25'
    d.close()
    assert d.isVisible() and not d._three_d._closed and source.read_bytes() == original
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d.close()
    assert not d.isVisible() and source.read_bytes() == original


def test_project_replacement_pauses_preview_but_preserves_unsaved_edits(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from suspensionlab.model.kim_format import write_document
    from suspensionlab.model.welded_arm import make_welded_arm

    c = controller()
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 10, 2, 'unknown', bends={
        'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
    }))
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    d._bend_editor.fields['front'][3].setText('25')
    c.new_project()
    assert d._candidate is None and not d._bend_editor.checks['front'].isEnabled()
    assert d._bend_editor.fields['front'][3].text() == '25' and d._edit_status.text()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    assert d.confirm_close() and d.shutdown()


def test_both_saved_tubes_and_save_dialog_changes(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSignalBlocker
    from PySide6.QtWidgets import QMessageBox

    from suspensionlab.model.kim_format import write_document
    from suspensionlab.model.welded_arm import make_welded_arm

    c = controller()
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 10, 2, 'unknown'))
    original = source.read_bytes()
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    for leg, values in [('front', ('100', '0', '0', '20')), ('rear', ('100', '-100', '0', '25'))]:
        d._bend_editor.checks[leg].setChecked(True)
        for field, value in zip(d._bend_editor.fields[leg], values, strict=True):
            field.setText(value)
    assert d._candidate is not None and all(p['version'] == '0.2' for p in d._candidate['parts'])
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(source), ''))
    d._save_copy()
    assert warnings and source.read_bytes() == original
    target = tmp_path / 'new.kima'
    def choose(*args):
        field = d._bend_editor.fields['rear'][3]
        with QSignalBlocker(field):
            field.setText('30')
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    d._save_copy()
    assert len(warnings) == 2 and not target.exists() and source.read_bytes() == original
    assert d._candidate['parts'][1]['geometry']['bend_radius_mm'] == 30
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    saved = read_document(target, 'assembly')
    assert saved['parts'][0]['geometry']['bend_radius_mm'] == 20
    assert saved['parts'][1]['geometry']['bend_radius_mm'] == 30
    d._bend_editor.checks['rear'].setChecked(False)
    assert d._candidate['version'] == '0.3' and d._candidate['parts'][1]['version'] == '0.1'
    d._bend_editor.checks['front'].setChecked(False)
    assert d._candidate['version'] == '0.2'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    assert d.confirm_close() and d.shutdown()


def test_close_confirmation_is_not_cached_after_failed_shutdown(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from suspensionlab.model.kim_format import write_document
    from suspensionlab.model.welded_arm import make_welded_arm

    c = controller()
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', make_welded_arm(c.project, 10, 2, 'unknown', bends={
        'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
    }))
    d = WeldmentDialog(c)
    qtbot.addWidget(d)
    d.show()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    d._bend_editor.fields['front'][3].setText('25')
    answers = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: answers.append(True) or QMessageBox.StandardButton.Yes)
    shutdown = d.shutdown
    monkeypatch.setattr(d, 'shutdown', lambda: False)
    d.close()
    assert d.isVisible() and len(answers) == 1
    monkeypatch.setattr(d, 'shutdown', shutdown)
    d.close()
    assert not d.isVisible() and len(answers) == 2
