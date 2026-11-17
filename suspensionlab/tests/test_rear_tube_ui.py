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
