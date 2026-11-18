"""Схема и частичный CAD передних труб; сохранение безопасной копии."""
import pytest
from PySide6.QtCore import QSettings, QSignalBlocker
from PySide6.QtWidgets import QFileDialog, QMessageBox

from suspensionlab.model.front_tube_arm import make_front_tube_arm
from suspensionlab.model.kim_format import read_document, write_document
from suspensionlab.model.niva_arm_views import FRONT
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.front_tubes_dialog import FrontTubesDialog
from suspensionlab.ui.main_window import MainWindow


def controller():
    c = AppController()
    for code, xyz in {'uca_f_in': (0., 0., 0.), 'uca_r_in': (0., -100., 0.), 'ubj': (100., 100., 0.),
                      'lca_f_in': (0., 0., 0.), 'lca_r_in': (0., -100., 0.), 'lbj': (100., 100., 0.)}.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    return c


def clean_close(d):
    d._baseline, d._saved_candidate, d._pending_project_changes = d._input_state(), None, False
    assert d.shutdown()
    d.close()


def test_menu_all_four_arms_live_and_invalid_bend_clear(qtbot, tmp_path):
    c = controller()
    before = c.project.to_dict()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    window.show()
    window.action_front_tubes.trigger()
    d = window._front_tubes_dialog
    assert d is not None and d._arm.count() == 4
    for index, key in enumerate(FRONT):
        d._arm.setCurrentIndex(index)
        assert d._candidate is not None and d._candidate['arm'] == key
        assert all(plan.view is not None and len(plan.paths) == 2 for plan in d._plans)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    editor = d._bend_editor
    editor.checks['front'].setChecked(True)
    assert d._candidate is None and all(plan.view is None for plan in d._plans) and not d._save.isEnabled()
    for field, value in zip(editor.fields['front'], ('100', '0', '0', '20'), strict=True):
        field.setText(value)
    assert d._candidate is not None and len(d._plans[0].paths[0]) > 3
    editor.fields['front'][3].setText('1000')
    assert d._candidate is None and d._three_d._document is None and not d._save.isEnabled()
    editor.fields['front'][3].setText('20')
    assert d._candidate is not None and c.project.to_dict() == before and not c.dirty
    clean_close(d)
    assert window._front_tubes_dialog is None
    window.close()


def test_open_both_bends_precision_change_and_new_copy(qtbot, tmp_path, monkeypatch):
    c = controller()
    bends = {'front': {'vertex_mm': [100.12345678901234, 0, 0], 'radius_mm': 20},
             'rear': {'vertex_mm': [100, -100, 0], 'radius_mm': 25}}
    doc = make_front_tube_arm(c.project, 'front_upper_left', 10.12345678901234, 2.12345678901234, bends)
    doc['name'] = 'Мой верхний рычаг'
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', doc)
    original, before = source.read_bytes(), c.project.to_dict()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    assert d._candidate == doc and not d._active and not d._save.isEnabled()
    assert not d._bend_editor.checks['front'].isEnabled() and float(d._radius.text()) == doc['radius_mm']
    d._start_preview()
    assert d._candidate == doc and not d._has_unsaved() and d._save.isEnabled()
    d._bend_editor.fields['rear'][3].setText('30')
    assert d._candidate['bends']['rear']['radius_mm'] == 30 and d._has_unsaved()
    target = tmp_path / 'new.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    saved = read_document(target, 'assembly')
    assert saved['name'] == doc['name'] and saved['radius_mm'] == doc['radius_mm']
    assert saved['wall_mm'] == doc['wall_mm'] and saved['bends']['front'] == doc['bends']['front']
    assert saved['bends']['rear']['radius_mm'] == 30 and not d._has_unsaved()
    assert source.read_bytes() == original and c.project.to_dict() == before and not c.dirty
    clean_close(d)


def test_source_protection_cancel_invalid_and_file_dialog_races(qtbot, tmp_path, monkeypatch):
    c = controller()
    doc = make_front_tube_arm(c.project, 'front_upper_left', 10, 2)
    source = tmp_path / 'source.kima'
    write_document(source, 'assembly', doc)
    original = source.read_bytes()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    d._start_preview()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(source), ''))
    d._save_copy()
    assert warnings and source.read_bytes() == original
    source.unlink()
    d._save_copy()
    assert len(warnings) == 2 and not source.exists()
    target = tmp_path / 'copy.kima'
    def choose(*args):
        with QSignalBlocker(d._radius):
            d._radius.setText('11')
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    d._save_copy()
    assert len(warnings) == 3 and not target.exists() and d._candidate['radius_mm'] == 11
    bad = tmp_path / 'bad.kima'
    bad.write_text('{"broken":true}', encoding='utf-8')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(bad), ''))
    d._open_file()
    assert len(warnings) == 4 and d._source == doc and d._radius.text() == '11'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._new_draft()
    assert d._source == doc and d._radius.text() == '11'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._new_draft()
    assert d._source is None and not d._has_unsaved() and d._candidate is not None
    clean_close(d)


def test_project_replacement_and_close_cancel_keep_loaded_edits(qtbot, tmp_path, monkeypatch):
    c = controller()
    doc = make_front_tube_arm(c.project, 'front_upper_left', 10, 2)
    path = tmp_path / 'source.kima'
    write_document(path, 'assembly', doc)
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d.show()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    d._start_preview()
    d._radius.setText('11')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d.close()
    assert d.isVisible() and not d._three_d._closed
    c.set_axle_type('front', 'macpherson_front')
    assert not d._active and d._candidate == doc and d._radius.text() == '11' and d._has_unsaved()
    d._start_preview()
    assert d._candidate is None and all(plan.view is None for plan in d._plans) and not d._save.isEnabled()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d.close()
    assert not d.isVisible()


def test_pair_mirror_reflects_both_bends_and_keeps_project(qtbot):
    c = controller()
    before = c.project.to_dict()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    for leg, values in [('front', ('100', '0', '0', '20')), ('rear', ('100', '-100', '0', '25'))]:
        d._bend_editor.checks[leg].setChecked(True)
        for field, value in zip(d._bend_editor.fields[leg], values, strict=True):
            field.setText(value)
    original = d._candidate
    assert original is not None and d._mirror.isEnabled()
    d._mirror.click()
    assert d._candidate['arm'] == 'front_upper_right'
    assert d._candidate['bends']['rear']['vertex_mm'] == [100, 100, 0]
    assert d._has_unsaved() and c.project.to_dict() == before
    d._mirror.click()
    assert d._candidate == original
    d._bend_editor.fields['front'][1].setText('not yet')
    assert not d._mirror.isEnabled() and d._candidate is None
    clean_close(d)


def test_auto_mirror_selection_preserves_precision_and_incomplete_input(qtbot, monkeypatch):
    c = controller()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    editor = d._bend_editor
    for leg, values in [('front', ('100', '0', '0', '20')), ('rear', ('100', '-100', '0', '25'))]:
        editor.checks[leg].setChecked(True)
        for field, value in zip(editor.fields[leg], values, strict=True):
            field.setText(value)
    assert d._candidate is not None and d._auto_mirror.isChecked()
    d._arm.setCurrentIndex(d._arm.findData('front_upper_right'))
    assert d._candidate is not None and d._candidate['bends']['rear']['vertex_mm'][1] == 100
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    assert d._candidate is not None and d._candidate['bends']['rear']['vertex_mm'][1] == -100
    editor.fields['rear'][1].setText('не готово')
    state = d._input_state()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d._arm.setCurrentIndex(d._arm.findData('front_upper_right'))
    assert warnings and d._input_state() == state and d._candidate is None
    d._auto_mirror.setChecked(False)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_right'))
    assert d._arm.currentData() == 'front_upper_right' and editor.fields['rear'][1].text() == 'не готово'
    clean_close(d)


def test_auto_mirror_is_not_applied_when_loading_a_snapshot(qtbot, tmp_path, monkeypatch):
    c = controller()
    doc = make_front_tube_arm(c.project, 'front_upper_right', 10, 2,
                              {'rear': {'vertex_mm': [100, 100, 0], 'radius_mm': 25}})
    source = tmp_path / 'right.kima'
    write_document(source, 'assembly', doc)
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    assert d._candidate == doc and d._bend_editor.fields['rear'][1].text() == '100'
    d._start_preview()
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    assert d._candidate is not None and d._candidate['bends']['rear']['vertex_mm'][1] == -100
    clean_close(d)


def test_live_mirror_save_reopen_edit_and_protect_pair(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.front_pair_snapshot import front_pair_sides

    c = controller()
    before = c.project.to_dict()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    for leg, values in [('front', ('100', '0', '0', '20')), ('rear', ('100', '-100', '0', '25'))]:
        d._bend_editor.checks[leg].setChecked(True)
        for field, value in zip(d._bend_editor.fields[leg], values, strict=True):
            field.setText(value)
    assert all(plan.view.key == 'front_upper_right' for plan in d._mirror_plans)
    old = d._pair_3d._document
    d._bend_editor.fields['rear'][3].setText('30')
    assert not d._pair_is_current(old)
    assert front_pair_sides(d._pair_3d._document)[1]['bends']['rear']['radius_mm'] == 30
    assert d._save_pair.isEnabled()
    path = tmp_path / 'pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_pair_copy()
    snapshot = read_document(path, 'assembly')
    assert snapshot['version'] == '0.7' and not d._has_unsaved()
    original = path.read_bytes()
    assert d.shutdown()
    d.close()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    assert not d._active and d._pair_3d._document == snapshot and d._candidate == snapshot['source']
    assert not d._save_pair.isEnabled() and not d._has_unsaved()
    d._start_preview()
    assert d._save_pair.isEnabled() and not d._has_unsaved()
    d._bend_editor.fields['rear'][3].setText('35')
    assert d._has_unsaved() and front_pair_sides(d._pair_3d._document)[1]['bends']['rear']['radius_mm'] == 35
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d._save_pair_copy()
    assert warnings and path.read_bytes() == original
    target = tmp_path / 'edited.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_pair_copy()
    updated = read_document(target, 'assembly')
    assert front_pair_sides(updated)[1]['bends']['rear']['radius_mm'] == 35
    assert not d._has_unsaved() and path.read_bytes() == original and c.project.to_dict() == before
    assert d.shutdown()
    d.close()


def test_single_save_does_not_mark_changed_pair_saved_and_dialog_race(qtbot, tmp_path, monkeypatch):
    c = controller()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    pair = tmp_path / 'pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(pair), ''))
    d._save_pair_copy()
    assert not d._has_unsaved() and read_document(pair, 'assembly')['version'] == '0.7'
    d._radius.setText('13')
    single = tmp_path / 'single.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(single), ''))
    d._save_copy()
    assert read_document(single, 'assembly')['version'] == '0.5' and d._has_unsaved()
    target, warnings = tmp_path / 'race.kima', []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    def change(*args):
        with QSignalBlocker(d._wall):
            d._wall.setText('3')
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', change)
    d._save_pair_copy()
    assert warnings and not target.exists() and d._has_unsaved()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._new_draft()
    assert d._wall.text() == '3'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._new_draft()
    assert d._saved_pair is None and not d._has_unsaved()
    assert d.shutdown()
    d.close()


def test_front_load_joints_save_layout_reopen_and_edit(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept

    c = controller()
    before = c.project.to_dict()
    ball_path, bush_path = tmp_path / 'ball.kima', tmp_path / 'bush.kima'
    ball, bush = make_joint_concept('ball', DEFAULTS['ball']), make_joint_concept('bushing', DEFAULTS['bushing'])
    write_document(ball_path, 'assembly', ball)
    write_document(bush_path, 'assembly', bush)
    originals = (ball_path.read_bytes(), bush_path.read_bytes())
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    assert not d._save_layout.isEnabled()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(ball_path), ''))
    d._load_joint('ball')
    assert d._joint_docs['ball'] == ball and d._has_unsaved() and not d._save_layout.isEnabled()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d._load_joint('bushing')
    assert warnings and d._joint_docs['bushing'] is None
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(bush_path), ''))
    d._load_joint('bushing')
    assert d._joint_docs['bushing'] == bush and d._save_layout.isEnabled()
    layout_path = tmp_path / 'layout.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(layout_path), ''))
    d._save_layout_copy()
    saved = read_document(layout_path, 'assembly')
    assert saved['version'] == '0.13' and saved['axis'] == 'x' and saved['ball'] == ball and saved['bushing'] == bush
    assert not d._has_unsaved()
    assert d.shutdown()
    d.close()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(layout_path), ''))
    d._open_file()
    assert not d._active and d._layout_3d._document == saved and not d._save_layout.isEnabled()
    assert not d._joint_buttons['ball'].isEnabled() and not d._has_unsaved()
    d._start_preview()
    assert d._save_layout.isEnabled() and not d._has_unsaved()
    d._radius.setText('13')
    assert d._has_unsaved() and d._layout_3d._document['pair']['source']['radius_mm'] == 13
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(layout_path), ''))
    d._save_layout_copy()
    assert len(warnings) == 2 and read_document(layout_path, 'assembly') == saved
    target = tmp_path / 'layout-copy.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_layout_copy()
    edited = read_document(target, 'assembly')
    assert edited['pair']['source']['radius_mm'] == 13 and edited['ball'] == ball and not d._has_unsaved()
    assert (ball_path.read_bytes(), bush_path.read_bytes()) == originals and c.project.to_dict() == before
    assert d.shutdown()
    d.close()


def test_joint_file_races_and_single_pair_save_leave_attachments_unsaved(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept

    c = controller()
    ball_path = tmp_path / 'ball.kima'
    write_document(ball_path, 'assembly', make_joint_concept('ball', DEFAULTS['ball']))
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    def select_with_change(*args):
        with QSignalBlocker(d._wall):
            d._wall.setText('3')
        return str(ball_path), ''
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', select_with_change)
    d._load_joint('ball')
    assert warnings and d._joint_docs['ball'] is None
    d._refresh()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(ball_path), ''))
    d._load_joint('ball')
    assert d._joint_docs['ball'] is not None and d._has_unsaved()
    pair = tmp_path / 'pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(pair), ''))
    d._save_pair_copy()
    assert read_document(pair, 'assembly')['version'] == '0.7' and d._has_unsaved()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._new_draft()
    assert d._joint_docs['ball'] is not None
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._new_draft()
    assert d._joint_docs['ball'] is None and not d._has_unsaved()
    assert d.shutdown()
    d.close()


def test_front_same_pair_save_open_and_mode_changes(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from suspensionlab.model.kim_format import read_document
    from suspensionlab.ui.front_tubes_dialog import FrontTubesDialog

    c = controller()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (0, -100, 0), 'ubj': (100, 100, 0)}.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    before = c.project.to_dict()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    assert d._save_pair.isEnabled() and d._has_unsaved()
    path = tmp_path / 'same.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_pair_copy()
    assert read_document(path, 'assembly')['version'] == '0.11' and not d._has_unsaved()
    original = path.read_bytes()
    assert d.shutdown()
    d.close()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    d._open_file()
    assert d._pair_mode.currentData() == 'same' and not d._active
    assert d._pair_3d._document['version'] == '0.11' and not d._save_pair.isEnabled()
    d._start_preview()
    assert d._save_pair.isEnabled() and not d._has_unsaved()
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('mirror'))
    assert d._pair_3d._document['version'] == '0.7' and d._has_unsaved()
    single = tmp_path / 'single.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(single), ''))
    d._save_copy()
    assert read_document(single, 'assembly')['version'] == '0.5' and d._has_unsaved()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._save_pair_copy()
    assert warnings and path.read_bytes() == original
    mirror = tmp_path / 'mirror.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(mirror), ''))
    d._save_pair_copy()
    assert read_document(mirror, 'assembly')['version'] == '0.7' and not d._has_unsaved()
    assert c.project.to_dict() == before and d.shutdown()
    d.close()


def test_front_same_rejects_collinear_but_single_stays_available(qtbot, monkeypatch):
    from suspensionlab.ui.front_tubes_dialog import FrontTubesDialog

    c = controller()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (100, 0, 0), 'ubj': (200, 0, 0)}.items():
        point = c.project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d._arm.setCurrentIndex(d._arm.findData('front_upper_left'))
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    assert d._candidate is not None and d._save.isEnabled() and not d._save_pair.isEnabled()
    assert d._pair_3d._document is None and all(p.view is None for p in d._mirror_plans)
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('mirror'))
    assert d._save_pair.isEnabled()
    d._baseline = d._input_state()
    d._pair_baseline = 'mirror'
    assert d.shutdown()
    d.close()


def test_front_pair_mode_race_and_existing_layout_remain_unsaved(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept

    c = controller()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    for kind in ('ball', 'bushing'):
        path = tmp_path / f'{kind}.kima'
        write_document(path, 'assembly', make_joint_concept(kind, DEFAULTS[kind]))
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args, path=path: (str(path), ''))
        d._load_joint(kind)
    layout = tmp_path / 'layout.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(layout), ''))
    d._save_layout_copy()
    assert not d._has_unsaved()
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    assert d._layout_3d._document['version'] == '0.14' and d._save_layout.isEnabled()
    pair = tmp_path / 'pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(pair), ''))
    d._save_pair_copy()
    assert read_document(pair, 'assembly')['version'] == '0.11' and d._has_unsaved()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    target = tmp_path / 'race.kima'
    def change(*args):
        with QSignalBlocker(d._pair_mode):
            d._pair_mode.setCurrentIndex(d._pair_mode.findData('mirror'))
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', change)
    d._save_pair_copy()
    assert warnings and not target.exists()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._new_draft()
    assert not d._has_unsaved() and d.shutdown()
    d.close()


def test_same_front_layout_save_open_edit_and_keep_sources(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept

    c = controller()
    before = c.project.to_dict()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    d._pair_mode.setCurrentIndex(d._pair_mode.findData('same'))
    inputs = []
    for kind in ('ball', 'bushing'):
        path = tmp_path / f'{kind}.kima'
        write_document(path, 'assembly', make_joint_concept(kind, DEFAULTS[kind]))
        inputs.append((path, path.read_bytes()))
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args, path=path: (str(path), ''))
        d._load_joint(kind)
    assert d._layout_3d._document['version'] == '0.14' and d._save_layout.isEnabled()
    target = tmp_path / 'same-layout.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_layout_copy()
    doc = read_document(target, 'assembly')
    assert doc['version'] == '0.14' and doc['axis'] == 'x' and doc['pair']['version'] == '0.11' and not d._has_unsaved()
    original = target.read_bytes()
    assert d.shutdown()
    d.close()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(target), ''))
    d._open_file()
    assert not d._active and d._layout_3d._document == doc and d._pair_mode.currentData() == 'same'
    assert not d._save_layout.isEnabled() and not d._has_unsaved()
    d._start_preview()
    assert d._save_layout.isEnabled() and not d._has_unsaved()
    d._radius.setText('13')
    assert d._has_unsaved() and d._layout_3d._document['pair']['source']['radius_mm'] == 13
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d._save_layout_copy()
    assert warnings and target.read_bytes() == original
    updated = tmp_path / 'new-layout.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(updated), ''))
    d._save_layout_copy()
    assert read_document(updated, 'assembly')['pair']['source']['radius_mm'] == 13 and not d._has_unsaved()
    assert all(path.read_bytes() == data for path, data in inputs) and c.project.to_dict() == before
    assert d.shutdown()
    d.close()


@pytest.mark.parametrize('same', [False, True])
def test_old_layout_axis_is_preserved_until_changed_and_saved_as_copy(qtbot, tmp_path, monkeypatch, same):
    from suspensionlab.model.front_joint_layout import make_front_joint_layout
    from suspensionlab.model.front_pair_snapshot import make_front_pair_snapshot
    from suspensionlab.model.front_same_pair import make_front_same_pair
    from suspensionlab.model.front_tube_arm import make_front_tube_arm
    from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept

    c = controller()
    arm = make_front_tube_arm(c.project, 'front_upper_left', 10, 2)
    pair = make_front_same_pair(arm) if same else make_front_pair_snapshot(arm)
    legacy = make_front_joint_layout(pair, make_joint_concept('ball', DEFAULTS['ball']),
                                     make_joint_concept('bushing', DEFAULTS['bushing']))
    source = tmp_path / 'old.kima'
    write_document(source, 'assembly', legacy, overwrite=False)
    original = source.read_bytes()
    d = FrontTubesDialog(c)
    qtbot.addWidget(d)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    d._open_file()
    assert d._bushing_axis.currentData() == 'y' and d._layout_3d._document == legacy
    assert not d._bushing_axis.isEnabled() and not d._has_unsaved()
    d._start_preview()
    assert d._layout_3d._document == legacy and not d._has_unsaved()
    d._bushing_axis.setCurrentIndex(d._bushing_axis.findData('x'))
    assert d._has_unsaved() and d._layout_3d._document['axis'] == 'x'
    assert d._layout_3d._document['version'] == ('0.14' if same else '0.13')
    pair_path = tmp_path / 'pair.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(pair_path), ''))
    d._save_pair_copy()
    assert d._has_unsaved()  # Pair does not contain bushing axis.
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    target = tmp_path / 'new.kima'
    def changed_in_modal(*args):
        with QSignalBlocker(d._bushing_axis):
            d._bushing_axis.setCurrentIndex(d._bushing_axis.findData('z'))
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', changed_in_modal)
    d._save_layout_copy()
    assert warnings and not target.exists()
    d._refresh()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_layout_copy()
    assert read_document(target, 'assembly')['axis'] == 'z' and not d._has_unsaved()
    assert source.read_bytes() == original
    assert d.shutdown()
    d.close()
