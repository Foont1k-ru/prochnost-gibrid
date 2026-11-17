"""Динамический условный эскиз не сохраняет CAD и не изменяет исходный проект."""
from PySide6.QtCore import QSettings, Qt

from suspensionlab.ui.arm_concept_dialog import ArmConceptDialog
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow


def test_open_live_nonmodal_and_follow_scheme_undo_redo(qtbot, tmp_path):
    c = AppController()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window._confirm_discard_changes = lambda: True
    window.show()
    before = c.project.to_dict()
    window.action_arm_concept.trigger()
    dialog = window._arm_concept_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert dialog.concept is not None and dialog.concept.style == 'tube'
    assert not c.dirty and c.project.to_dict() == before
    # Reopening does not duplicate the live window.
    window.action_arm_concept.trigger()
    assert window._arm_concept_dialog is dialog
    point = c.project.front.hardpoints['lbj']
    initial = point.as_tuple()
    old = dialog.concept.points[2]
    c.move_point(point, (initial[0] + 20, initial[1], initial[2]))
    assert dialog.concept is not None and dialog.concept.points[2][0] == old[0] + 20
    c.undo_last()
    assert dialog.concept is not None and dialog.concept.points[2] == old
    c.redo_last()
    assert dialog.concept is not None and dialog.concept.points[2][0] == old[0] + 20
    # Exercise paintEvent in the offscreen Qt backend.
    assert not dialog._canvas.grab().isNull()
    dialog.close()
    assert window._arm_concept_dialog is None
    c.dirty = False


def test_variant_and_dimension_edits_never_change_project(qtbot):
    c = AppController()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    dialog.show()
    before = c.project.to_dict()
    assert dialog.concept is not None and dialog.concept.style == 'tube'
    dialog._radius.setValue(15.)
    dialog._wall.setValue(15.)
    assert dialog.concept is None and dialog._canvas.concept is None
    assert 'недоступен' in dialog._status.text()
    dialog._style.setCurrentIndex(1)
    assert dialog.concept is not None and dialog.concept.style == 'sheet'
    assert not dialog._radius.isEnabled() and dialog._sheet.isEnabled()
    dialog._sheet.setValue(4.)
    assert dialog.concept is not None and dialog.concept.sheet_mm == 4.
    assert not dialog._canvas.grab().isNull()
    assert not c.dirty and c.project.to_dict() == before


def test_invalid_points_or_suspension_clear_old_result_and_recover(qtbot):
    c = AppController()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    old = dialog.concept
    assert old is not None
    first = c.project.front.hardpoints['lca_f_in']
    outer = c.project.front.hardpoints['lbj']
    original = first.as_tuple()
    c.move_point(first, outer.as_tuple())
    assert dialog.concept is None and dialog._canvas.concept is None and not dialog._summary.text()
    c.move_point(first, original)
    assert dialog.concept is not None and dialog.concept.points == old.points
    c.set_axle_type('front', 'multilink_front')
    assert dialog.concept is None and dialog._canvas.concept is None
    c.new_project()
    assert dialog.concept is not None
    assert not c.dirty


def test_save_tube_snapshot_tracks_current_scheme_but_is_not_live(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from suspensionlab.model.kim_format import compare_lower_arm_source, read_document

    c = AppController()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    dialog.show()
    before = c.project.to_dict()
    path = tmp_path / 'нижний передний'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    dialog._radius.setValue(20.)
    dialog._wall.setValue(2.5)
    assert dialog._save_tube.isEnabled()
    dialog._save_tube.click()
    actual = path.with_name(path.name + '.kim')
    saved = read_document(actual, 'part')
    assert saved['geometry']['kind'] == 'prototype_lower_arm_tubes'
    assert saved['geometry']['radius_mm'] == 20. and saved['geometry']['wall_mm'] == 2.5
    assert compare_lower_arm_source(saved, c.project)
    assert 'автоматически не обновляется' in dialog._save_status.text()
    assert c.project.to_dict() == before and not c.dirty and c.project.path is None
    old_bytes = actual.read_bytes()
    point = c.project.front.hardpoints['lbj']
    c.move_point(point, (point.x, point.y + 50, point.z))
    assert dialog.concept is not None and not compare_lower_arm_source(saved, c.project)
    assert actual.read_bytes() == old_bytes and not dialog._save_status.text()
    dialog._style.setCurrentIndex(1)
    assert not dialog._save_tube.isEnabled()


def test_save_rejects_changes_while_file_dialog_is_open(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    c = AppController()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    target = tmp_path / 'arm.kim'
    def choose(*args):
        point = c.project.front.hardpoints['lbj']
        c.move_point(point, (point.x, point.y + 1, point.z))
        return str(target), ''
    warnings = []
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    dialog._save_tube_snapshot()
    assert warnings and 'изменились' in warnings[0][2] and not target.exists()
    assert c.dirty


def test_export_refuses_hardlinks_to_project_and_autosave(qtbot, tmp_path, monkeypatch):
    import os

    import pytest
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from suspensionlab.ui import controller as module

    backup = tmp_path / 'auto.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    c = AppController()
    project_file = c.save_project(tmp_path / 'project')
    assert c.autosave()
    old_project, old_backup = project_file.read_bytes(), backup.read_bytes()
    alias = tmp_path / 'target.kim'
    try:
        os.link(project_file, alias)
    except OSError:
        pytest.skip('Hard links are unavailable')
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    warnings = []
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(alias), ''))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    dialog._save_tube_snapshot()
    assert warnings and project_file.read_bytes() == old_project and alias.read_bytes() == old_project
    alias.unlink()
    os.link(backup, alias)
    dialog._save_tube_snapshot()
    assert len(warnings) == 2 and backup.read_bytes() == old_backup and alias.read_bytes() == old_backup


def test_save_weldment_is_explicit_incomplete_and_does_not_change_project(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from suspensionlab.model.kim_format import read_document
    from suspensionlab.model.welded_arm import weldment_source_matches

    c = AppController()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    before = c.project.to_dict()
    dialog._damper.setCurrentIndex(1)
    path = tmp_path / 'нижний рычаг'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    assert dialog._save_assembly.isEnabled()
    dialog._save_assembly.click()
    target = path.with_name(path.name + '.kima')
    doc = read_document(target, 'assembly')
    assert doc['version'] == '0.2' and doc['damper_mount'] == 'required'
    assert [p['geometry']['leg'] for p in doc['parts']] == ['front', 'rear']
    assert any(n['id'] == 'damper_bracket' and n['kind'] == 'unresolved' for n in doc['nodes'])
    assert weldment_source_matches(doc)
    assert 'не спроектированы' in dialog._save_status.text()
    assert not c.dirty and c.project.to_dict() == before and c.project.path is None
    old = target.read_bytes()
    point = c.project.front.hardpoints['lbj']
    c.move_point(point, (point.x, point.y + 10, point.z))
    assert target.read_bytes() == old and not dialog._save_status.text()
    dialog._style.setCurrentIndex(1)
    assert not dialog._save_assembly.isEnabled()


def test_weldment_save_rejects_choice_change_during_file_dialog(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    c = AppController()
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    target = tmp_path / 'arm.kima'
    def choose(*args):
        dialog._damper.setCurrentIndex(1)
        return str(target), ''
    warnings = []
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    dialog._save_weldment_snapshot()
    assert warnings and 'изменились' in warnings[0][2] and not target.exists()
    assert not c.dirty


def test_weldment_save_refuses_hardlinks_to_project_and_autosave(qtbot, tmp_path, monkeypatch):
    import os

    import pytest
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from suspensionlab.ui import controller as module

    backup = tmp_path / 'auto.susp.json'
    monkeypatch.setattr(module, 'autosave_path', lambda: backup)
    c = AppController()
    project_file = c.save_project(tmp_path / 'project')
    assert c.autosave()
    old_project, old_backup = project_file.read_bytes(), backup.read_bytes()
    alias = tmp_path / 'target.kima'
    try:
        os.link(project_file, alias)
    except OSError:
        pytest.skip('Hard links are unavailable')
    dialog = ArmConceptDialog(c)
    qtbot.addWidget(dialog)
    warnings = []
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(alias), ''))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    dialog._save_weldment_snapshot()
    assert warnings and project_file.read_bytes() == old_project and alias.read_bytes() == old_project
    alias.unlink()
    os.link(backup, alias)
    dialog._save_weldment_snapshot()
    assert len(warnings) == 2 and backup.read_bytes() == old_backup and alias.read_bytes() == old_backup
