"""Ввод, актуальность и сохранение только новой копии задней трубы."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QFileDialog, QMessageBox

from suspensionlab.model.kim_format import read_document
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.rear_tube_dialog import RearTubeDialog


def controller():
    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    for code, xyz in {'ll_in_l': (0., 0., 0.), 'll_out_l': (100., 100., 0.)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    c.dirty = False
    return c


def test_rear_editor_live_bend_and_new_copy(qtbot, tmp_path, monkeypatch):
    c = controller()
    before = c.project.to_dict()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    assert d._candidate is not None and d._save.isEnabled()
    d._bend.setChecked(True)
    assert d._candidate is None and all(plan.view is None for plan in d._plans) and not d._save.isEnabled()
    for field, value in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    assert d._candidate is not None and len(d._plans[0].path) > 3
    path = tmp_path / 'new.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_copy()
    saved = read_document(path, 'assembly')
    assert saved['arm'] == 'rear_lower_left' and saved['bend']['radius_mm'] == 20
    assert c.project.to_dict() == before and not c.dirty
    original = path.read_bytes()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d._save_copy()
    assert warnings and path.read_bytes() == original
    d._fields[3].setText('1000')
    assert d._candidate is None and d._three_d._document is None and not d._save.isEnabled()
    d._fields[3].setText('20')
    p = c.project.rear.hardpoints['ll_out_l']
    c.move_point(p, (100, 10, 0))
    assert d._candidate is None and path.read_bytes() == original
    d._baseline, d._saved_candidate = d._input_state(), None
    d._pair_baseline = d._pair_state()
    assert d.shutdown()
    d.close()


def test_input_changed_during_save_even_without_signal(qtbot, tmp_path, monkeypatch):
    c = controller()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._bend.setChecked(True)
    for field, value in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    target = tmp_path / 'no-write.kima'
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    def choose(*args):
        with QSignalBlocker(d._fields[3]):
            d._fields[3].setText('25')
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    d._save_copy()
    assert warnings and not target.exists() and d._candidate['bend']['radius_mm'] == 25
    c.set_axle_type('rear', 'multilink_rear')
    assert d._candidate is None and d._three_d._document is None and not d._save.isEnabled()
    d._baseline, d._saved_candidate = d._input_state(), None
    d._pair_baseline = d._pair_state()
    assert d.shutdown()
    d.close()


def test_close_confirmation_and_project_replacement(qtbot, monkeypatch):
    c = controller()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d.show()
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    assert d._edit_status.text()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d.close()
    assert d.isVisible() and not d._three_d._closed
    c.set_axle_type('rear', 'multilink_rear')
    assert d._candidate is None and d._edit_status.text()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d.close()
    assert not d.isVisible()


def rear_snapshot(c, path, *, curved=True):
    from suspensionlab.model.kim_format import write_document
    from suspensionlab.model.rear_tube import make_rear_tube

    bend = {'vertex_mm': [100.12345678901234, 0., 0.], 'radius_mm': 20.12345678901234} if curved else None
    doc = make_rear_tube(c.project, 'rear_lower_left', 10.12345678901234, 2.12345678901234, bend)
    doc['name'] = 'Моя задняя тяга'
    write_document(path, 'assembly', doc)
    return doc


def test_open_saved_preview_edit_and_save_new_copy(qtbot, tmp_path, monkeypatch):
    c = controller()
    source = tmp_path / 'source.kima'
    doc = rear_snapshot(c, source)
    original, before = source.read_bytes(), c.project.to_dict()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    assert d._source == doc and not d._active and d._candidate == doc
    assert all(plan.view is not None for plan in d._plans) and not d._save.isEnabled()
    assert not d._radius.isEnabled() and d._activate.isEnabled()
    assert float(d._radius.text()) == doc['radius_mm'] and float(d._wall.text()) == doc['wall_mm']
    d._start_preview()
    assert d._active and d._candidate == doc and d._save.isEnabled() and not d._has_unsaved()
    d._fields[3].setText('25')
    assert d._candidate['bend']['radius_mm'] == 25 and d._has_unsaved()
    target = tmp_path / 'edited.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    new = read_document(target, 'assembly')
    assert new['name'] == doc['name'] and new['radius_mm'] == doc['radius_mm']
    assert new['wall_mm'] == doc['wall_mm'] and new['bend']['vertex_mm'] == doc['bend']['vertex_mm']
    assert new['bend']['radius_mm'] == 25 and not d._has_unsaved()
    assert source.read_bytes() == original and c.project.to_dict() == before and not c.dirty
    assert d.shutdown()
    d.close()


def test_open_cancel_and_failed_file_do_not_discard_current_work(qtbot, tmp_path, monkeypatch):
    c = controller()
    good = tmp_path / 'good.kima'
    rear_snapshot(c, good, curved=False)
    bad = tmp_path / 'bad.kima'
    bad.write_text('{"broken":true}', encoding='utf-8')
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._radius.setText('15')
    before = d._candidate
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(bad), ''))
    d._open_file()
    assert warnings and d._source is None and d._candidate == before and d._radius.text() == '15'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(good), ''))
    d._open_file()
    assert d._source is None and d._radius.text() == '15'
    def choose(*args):
        with QSignalBlocker(d._radius):
            d._radius.setText('16')
        return str(good), ''
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', choose)
    d._open_file()
    assert len(warnings) == 2 and d._source is None and d._radius.text() == '16'
    d._baseline, d._saved_candidate = d._input_state(), None
    d._pair_baseline = d._pair_state()
    assert d.shutdown()
    d.close()


def test_original_paths_and_deleted_source_are_protected(qtbot, tmp_path, monkeypatch):
    import os

    c = controller()
    source = tmp_path / 'source.kima'
    rear_snapshot(c, source, curved=False)
    original = source.read_bytes()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(source), ''))
    d._save_copy()
    assert len(warnings) == 1 and source.read_bytes() == original
    alias = tmp_path / 'hardlink.kima'
    try:
        os.link(source, alias)
    except OSError:
        alias = None
    if alias is not None:
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(alias), ''))
        d._save_copy()
        assert len(warnings) == 2 and alias.read_bytes() == original
    source.unlink()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(source), ''))
    d._save_copy()
    assert not source.exists() and len(warnings) == (3 if alias is not None else 2)
    d._baseline, d._saved_candidate = d._input_state(), None
    d._pair_baseline = d._pair_state()
    assert d.shutdown()
    d.close()


def test_loaded_edits_survive_project_replacement_but_need_reactivation(qtbot, tmp_path, monkeypatch):
    c = controller()
    source = tmp_path / 'source.kima'
    original_doc = rear_snapshot(c, source)
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    d._fields[3].setText('25')
    assert d._candidate['bend']['radius_mm'] == 25 and d._has_unsaved()
    c.new_project()
    assert not d._active and d._candidate == original_doc and not d._save.isEnabled()
    assert not d._fields[3].isEnabled() and d._fields[3].text() == '25' and d._has_unsaved()
    d._start_preview()
    assert d._candidate is None and all(plan.view is None for plan in d._plans)
    assert d._fields[3].text() == '25' and not d._save.isEnabled()
    d._baseline, d._saved_candidate, d._pending_project_changes = d._input_state(), None, False
    assert d.shutdown()
    d.close()


def test_loaded_incomplete_and_invalid_fields_clear_preview_and_block_save(qtbot, tmp_path, monkeypatch):
    c = controller()
    source = tmp_path / 'source.kima'
    rear_snapshot(c, source)
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    d._radius.clear()
    assert d._candidate is None and d._three_d._document is None and not d._save.isEnabled()
    d._radius.setText('10,5')
    assert d._candidate is not None
    d._fields[3].setText('1000')
    assert d._candidate is None and all(plan.view is None for plan in d._plans)
    d._bend.setChecked(False)
    assert d._candidate is not None and d._candidate['bend'] is None
    d._baseline, d._saved_candidate = d._input_state(), None
    d._pair_baseline = d._pair_state()
    assert d.shutdown()
    d.close()


def test_reopened_source_and_current_project_are_explicitly_distinguished(qtbot, tmp_path, monkeypatch):
    c = controller()
    source = tmp_path / 'source.kima'
    saved = rear_snapshot(c, source)
    c.project.rear.hardpoints['ll_out_l'].y = 140
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    assert d._candidate == saved and not d._active and not d._save.isEnabled()
    assert d._plans[0].view.points[1][1] == 100
    d._start_preview()
    assert d._candidate != saved and d._plans[0].view.points[1][1] == 140
    assert 'отлич' in d._status.text() and d._has_unsaved()
    target = tmp_path / 'changed.kima'
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    def choose(*args):
        c.project.rear.hardpoints['ll_out_l'].y += 1  # change without a Qt signal
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    d._save_copy()
    assert warnings and not target.exists() and d._candidate['scheme'] != saved['scheme']
    d._baseline, d._saved_candidate, d._pending_project_changes = d._input_state(), None, False
    assert d.shutdown()
    d.close()


def test_new_draft_confirms_unsaved_changes_and_resets_file(qtbot, tmp_path, monkeypatch):
    c = controller()
    source = tmp_path / 'source.kima'
    doc = rear_snapshot(c, source)
    original = source.read_bytes()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    d._radius.setText('15')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._new_draft()
    assert d._source == doc and d._radius.text() == '15' and d._has_unsaved()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._new_draft()
    assert d._source is None and d._source_paths == () and d._active
    assert d._radius.text() == '12' and d._wall.text() == '2' and not d._bend.isChecked()
    assert d._candidate is not None and not d._has_unsaved() and source.read_bytes() == original
    assert d.shutdown()
    d.close()


def test_pair_modes_keep_tube_identity_or_mirror_and_preserve_source(qtbot, tmp_path, monkeypatch):
    c = controller()
    for code, xyz in {'ll_in_r': (0., 0., 0.), 'll_out_r': (100., -100., 0.)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    before = c.project.to_dict()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._bend.setChecked(True)
    for field, text in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(text)
    assert not d._pair.isEnabled()
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    assert d._pair.isEnabled() and d._pair_roll.isEnabled()
    d._pair.click()
    assert d._arm.currentData() == 'rear_lower_right'
    assert abs(float(d._fields[0].text())) < 1e-8 and float(d._fields[1].text()) == -100
    assert d._has_unsaved() and d._candidate['arm'] == 'rear_lower_right'
    path = tmp_path / 'right.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_copy()
    assert read_document(path, 'assembly') == d._candidate
    d._pair.click()
    assert d._arm.currentData() == 'rear_lower_left' and float(d._fields[0].text()) == 100
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('mirror'))
    assert not d._pair_roll.isEnabled()
    d._pair.click()
    assert d._arm.currentData() == 'rear_lower_right' and float(d._fields[0].text()) == 100
    assert d._fields[1].text() in ('-0.0', '0.0')
    assert c.project.to_dict() == before and not c.dirty
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    c.project.rear.hardpoints['ll_in_l'].y = 5
    d._refresh()
    state = d._input_state()
    d._pair.click()
    assert warnings and d._input_state() == state and d._arm.currentData() == 'rear_lower_right'
    d._arm.setCurrentIndex(d._arm.findData('panhard'))
    assert not d._pair.isEnabled() and not d._pair_mode.isEnabled()
    d._baseline, d._saved_candidate = d._input_state(), None
    d._pair_baseline = d._pair_state()
    assert d.shutdown()
    d.close()


def test_pair_preview_tracks_edits_and_invalidity_without_modifying_project(qtbot):
    c = controller()
    for code, xyz in {'ll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    before = c.project.to_dict()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._bend.setChecked(True)
    for field, text in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(text)
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('mirror'))
    assert all(plan.view is not None and plan.view.key == 'rear_lower_right' for plan in d._pair_plans)
    mirrored = d._pair_three_d._document
    assert mirrored['bend']['vertex_mm'] == [100, 0, 0]
    d._fields[3].setText('30')
    assert d._pair_three_d._document['bend']['radius_mm'] == 30
    assert not d._pair_is_current(mirrored)
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    assert abs(d._pair_three_d._document['bend']['vertex_mm'][0]) < 1e-8
    d._pair_roll.setText('90')
    assert d._pair_three_d._document is not None and d._pair_plans[0].view is not None
    d._pair_roll.setText('invalid')
    assert d._candidate is not None and d._pair_three_d._document is None
    assert all(plan.view is None for plan in d._pair_plans)
    d._pair_roll.setText('0')
    assert d._pair_three_d._document is not None
    d._fields[3].setText('invalid')
    assert d._candidate is None and d._pair_three_d._document is None
    assert all(plan.view is None for plan in d._pair_plans)
    assert c.project.to_dict() == before
    d._baseline, d._saved_candidate = d._input_state(), None
    d._pair_baseline = d._pair_state()
    assert d.shutdown()
    d.close()


def test_save_open_and_edit_linked_pair_with_protected_source(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.rear_pair_snapshot import rear_pair_sides

    c = controller()
    for code, xyz in {'ll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    original_project = c.project.to_dict()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._bend.setChecked(True)
    for field, value in zip(d._fields, ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    d._pair_roll.setText('45')
    assert d._has_unsaved() and d._save_pair.isEnabled()
    path = tmp_path / 'pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_pair_copy()
    saved = read_document(path, 'assembly')
    assert saved['version'] == '0.6' and saved['mode'] == 'same' and saved['roll_degrees'] == 45
    assert not d._has_unsaved()
    original = path.read_bytes()
    assert d.shutdown()
    d.close()
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    assert d._source_pair == saved and d._candidate == saved['source'] and not d._active
    assert d._pair_mode.currentData() == 'same' and d._pair_roll.text() == '45.0'
    assert d._pair_three_d._document == rear_pair_sides(saved)[1] and not d._save_pair.isEnabled()
    d._start_preview()
    assert d._save_pair.isEnabled() and not d._has_unsaved()
    d._fields[3].setText('30')
    assert d._pair_three_d._document['bend']['radius_mm'] == 30 and d._has_unsaved()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_pair_copy()
    assert warnings and path.read_bytes() == original
    copy = tmp_path / 'new-pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(copy), ''))
    d._save_pair_copy()
    updated = read_document(copy, 'assembly')
    assert rear_pair_sides(updated)[1]['bend']['radius_mm'] == 30
    assert updated['mode'] == 'same' and updated['roll_degrees'] == 45 and not d._has_unsaved()
    assert path.read_bytes() == original and c.project.to_dict() == original_project and not c.dirty
    assert d.shutdown()
    d.close()


def test_pair_changes_cannot_be_discarded_by_saving_single_or_nested_dialog(qtbot, tmp_path, monkeypatch):
    c = controller()
    for code, xyz in {'ll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    d._pair_roll.setText('45')
    pair = tmp_path / 'pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(pair), ''))
    d._save_pair_copy()
    assert not d._has_unsaved()
    d._pair_roll.setText('30')
    assert d._has_unsaved()
    single = tmp_path / 'single.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(single), ''))
    d._save_copy()
    assert read_document(single, 'assembly')['version'] == '0.4' and d._has_unsaved()
    target = tmp_path / 'not-created.kima'
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    def change_during_save(*args):
        with QSignalBlocker(d._pair_roll):
            d._pair_roll.setText('60')
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', change_during_save)
    d._save_pair_copy()
    assert warnings and not target.exists() and d._has_unsaved()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._new_draft()
    assert d._arm.currentData() == 'rear_lower_left' and d._pair_roll.text() == '60'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._new_draft()
    assert not d._has_unsaved() and d._pair_mode.currentData() == ''
    assert d.shutdown()
    d.close()


def test_replacement_demands_confirmation_for_unsaved_pair_rule(qtbot, tmp_path, monkeypatch):
    c = controller()
    for code, xyz in {'ll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
        point = c.project.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = RearTubeDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('rear_lower_left'))
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('mirror'))
    path = tmp_path / 'pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_pair_copy()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    d._start_preview()
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    c.set_axle_type('rear', 'multilink_rear')
    assert not d._active and d._has_unsaved() and d._pair_mode.currentData() == 'same'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._new_draft()
    assert d._source_pair is not None and d._has_unsaved()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._new_draft()
    assert d._source is None and not d._has_unsaved()
    assert d.shutdown()
    d.close()
