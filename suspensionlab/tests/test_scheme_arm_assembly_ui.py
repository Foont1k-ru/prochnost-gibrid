"""Сборка рычага из отдельных файлов: создание, открытие, безопасность."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from suspensionlab.model.kim_format import read_document, write_document
from suspensionlab.model.scheme_arm_assembly import make_scheme_arm_assembly
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow
from suspensionlab.ui.scheme_arm_assembly_dialog import (
    NewAssemblyParametersDialog,
    SchemeArmAssemblyDialog,
)


def make_doc(c):
    return make_scheme_arm_assembly(c.project, 12, 2, {'axis': 'x', 'outer_radius_mm': 14,
                                                        'bore_radius_mm': 7, 'length_mm': 24})


def test_new_parameters_validate_both_tubes_and_bushings(qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = NewAssemblyParametersDialog(parent)
    dialog.show()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    dialog.wall.setText('15')
    dialog.accept()
    assert dialog.isVisible() and warnings
    dialog.wall.setText('2')
    dialog.fields['bore_radius_mm'].setText('15')
    dialog.accept()
    assert dialog.isVisible() and len(warnings) == 2
    dialog.fields['bore_radius_mm'].setText('7')
    dialog.accept()
    assert not dialog.isVisible() and dialog.tube_values() == (12, 2)


def test_create_from_live_scheme_and_open_menu(qtbot, tmp_path, monkeypatch):
    c = AppController()
    before = deepcopy(c.project.to_dict())
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    opened = []
    monkeypatch.setattr(NewAssemblyParametersDialog, 'exec', lambda d: QDialog.DialogCode.Accepted)
    def show_assembly(d):
        opened.append(deepcopy(d.document))
        assert d.three_d.shutdown()
        return 0
    monkeypatch.setattr(SchemeArmAssemblyDialog, 'exec', show_assembly)
    window.action_new_scheme_assembly.trigger()
    assert len(opened) == 1 and opened[0]['version'] == '0.15' and opened[0]['axis'] == 'x'
    path = tmp_path / 'assembly.kima'
    write_document(path, 'assembly', opened[0], overwrite=False)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    window.action_open_scheme_assembly.trigger()
    assert opened[1] == opened[0] and c.project.to_dict() == before and not c.dirty
    window.close()


def test_save_reopen_export_all_parts_and_rebuild_without_overwriting(qtbot, tmp_path, monkeypatch):
    c = AppController()
    doc = make_doc(c)
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    assert d.document != d._saved and d.three_d._document == doc
    target = tmp_path / 'new.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    assert read_document(target, 'assembly') == doc and d._saved == d.document
    raw = target.read_bytes()
    for index, part in enumerate(doc['parts']):
        d.part_choice.setCurrentIndex(index)
        out = tmp_path / f'part-{index}.kim'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, out=out: (str(out), ''))
        d._export_part()
        assert read_document(out, 'part') == part
    assert target.read_bytes() == raw
    assert d.three_d.shutdown()
    d.close()
    d = SchemeArmAssemblyDialog(c, read_document(target, 'assembly'), target)
    qtbot.addWidget(d)
    point = c.project.front.hardpoints['lca_f_in']
    c.move_point(point, (point.x + 20, point.y, point.z))
    assert 'различаются' in d.source_status.text()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._apply_current_scheme()
    assert d.document != d._saved and d.document['parts'][2:] == doc['parts'][2:]
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    d._save_copy()
    assert warnings and target.read_bytes() == raw
    copy_path = tmp_path / 'updated.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(copy_path), ''))
    d._save_copy()
    assert read_document(copy_path, 'assembly') == d.document and target.read_bytes() == raw
    assert d.three_d.shutdown()
    d.close()


def test_modal_races_do_not_save_or_overwrite(qtbot, tmp_path, monkeypatch):
    c = AppController()
    doc = make_doc(c)
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    target = tmp_path / 'race.kima'
    def race_save(*args):
        d.document['name'] = 'Изменено'
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', race_save)
    d._save_copy()
    assert warnings and not target.exists()
    part_path = tmp_path / 'part.kim'
    def race_export(*args):
        d.part_choice.setCurrentIndex(1)
        return str(part_path), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', race_export)
    d._export_part()
    assert len(warnings) == 2 and not part_path.exists()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    assert not d._confirm_close()
    d._saved = deepcopy(d.document)
    assert d.three_d.shutdown()
    d.close()


def test_edit_selected_parts_axis_rebuild_and_save_copy(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui.scheme_arm_assembly_dialog import PartDimensionsDialog

    c = AppController()
    doc = make_doc(c)
    path = tmp_path / 'source.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    original = path.read_bytes()
    d = SchemeArmAssemblyDialog(c, doc, path)
    qtbot.addWidget(d)
    def edit(dialog):
        if dialog.identifier == 'tube_front':
            dialog.fields['radius_mm'].setText('15,123456789')
            dialog.fields['wall_mm'].setText('3')
        else:
            dialog.fields['length_mm'].setText('31')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PartDimensionsDialog, 'exec', edit)
    d._edit_selected_part()
    assert d.document['parts'][0]['geometry']['radius_mm'] == 15.123456789
    assert d.document['parts'][1] == doc['parts'][1] and d.document != d._saved
    d.part_choice.setCurrentIndex(2)
    d._edit_selected_part()
    assert d.document['parts'][2]['geometry']['length_mm'] == 31
    assert d.document['parts'][3] == doc['parts'][3]
    assert '31' in d.part_info.text()
    d.axis.setCurrentIndex(d.axis.findData('z'))
    assert d.document['axis'] == 'z'
    point = c.project.front.hardpoints['lca_f_in']
    c.move_point(point, (point.x + 30, point.y, point.z))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._apply_current_scheme()
    assert d.document['parts'][0]['geometry']['radius_mm'] == 15.123456789
    assert d.document['parts'][2]['geometry']['length_mm'] == 31 and d.document['axis'] == 'z'
    out = tmp_path / 'changed.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(out), ''))
    d._save_copy()
    assert read_document(out, 'assembly') == d.document and path.read_bytes() == original
    assert d.three_d.shutdown()
    d.close()


def test_edit_parameter_dialog_checks_and_races(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from suspensionlab.ui.scheme_arm_assembly_dialog import PartDimensionsDialog

    parent = QWidget()
    qtbot.addWidget(parent)
    c = AppController()
    doc = make_doc(c)
    dialog = PartDimensionsDialog(doc, 'tube_front', parent)
    dialog.show()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    dialog.fields['wall_mm'].setText('12')
    dialog.accept()
    assert warnings and dialog.isVisible()
    dialog.fields['wall_mm'].setText('2,5')
    dialog.accept()
    assert not dialog.isVisible() and dialog.values()['wall_mm'] == 2.5
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    def edit_with_race(form):
        form.fields['radius_mm'].setText('20')
        d.axis.setCurrentIndex(d.axis.findData('y'))
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PartDimensionsDialog, 'exec', edit_with_race)
    d._edit_selected_part()
    assert len(warnings) == 2 and d.document['parts'][0] == doc['parts'][0] and d.document['axis'] == 'y'
    d._saved = deepcopy(d.document)
    assert d.three_d.shutdown()
    d.close()


def test_import_explicit_confirmation_races_and_source_protection(qtbot, tmp_path, monkeypatch):
    c = AppController()
    doc = make_doc(c)
    original = deepcopy(doc)
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    d.part_choice.setCurrentIndex(2)
    replacement = deepcopy(doc['parts'][3])
    replacement['name'] = 'Запасной корпус'
    replacement['geometry']['length_mm'] = 40
    source = tmp_path / 'input.kim'
    write_document(source, 'part', replacement, overwrite=False)
    raw = source.read_bytes()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._import_selected_part()
    assert d.document == original
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._import_selected_part()
    assert d.document['parts'][2]['id'] == 'housing_front'
    assert d.document['parts'][2]['name'] == 'Запасной корпус' and d.document['parts'][2]['geometry']['length_mm'] == 40
    assert d.document['parts'][3] == original['parts'][3] and source.read_bytes() == raw
    assert d.part_choice.currentText() == 'Запасной корпус' and d.document != d._saved
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(source), ''))
    d._export_part()
    assert warnings and source.read_bytes() == raw
    bad = tmp_path / 'wrong.kim'
    write_document(bad, 'part', doc['parts'][0], overwrite=False)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(bad), ''))
    state = deepcopy(d.document)
    d._import_selected_part()
    assert len(warnings) == 2 and d.document == state
    changed = tmp_path / 'changed.kim'
    imported = deepcopy(replacement)
    imported['geometry']['length_mm'] = 45
    write_document(changed, 'part', imported, overwrite=False)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(changed), ''))
    def modify_file(*args):
        altered = deepcopy(imported)
        altered['geometry']['length_mm'] = 46
        write_document(changed, 'part', altered)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', modify_file)
    d._import_selected_part()
    assert len(warnings) == 3 and d.document == state
    d._saved = deepcopy(d.document)
    assert d.three_d.shutdown()
    d.close()


def test_stale_tube_import_rejected_and_current_rebuild_preserves_import(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.scheme_arm_assembly import edit_assembly_part

    c = AppController()
    doc = make_doc(c)
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    imported = edit_assembly_part(doc, 'tube_front', {'radius_mm': 19, 'wall_mm': 3})['parts'][0]
    path = tmp_path / 'tube.kim'
    write_document(path, 'part', imported, overwrite=False)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._import_selected_part()
    assert d.document['parts'][0]['geometry']['radius_mm'] == 19
    point = c.project.front.hardpoints['lbj']
    c.move_point(point, (point.x, point.y + 40, point.z))
    d._apply_current_scheme()
    assert d.document['parts'][0]['geometry']['radius_mm'] == 19
    state = deepcopy(d.document)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d._import_selected_part()  # old file's points conflict with updated scheme
    assert warnings and d.document == state
    d._saved = deepcopy(d.document)
    assert d.three_d.shutdown()
    d.close()


def test_plate_add_edit_rebuild_export_save_reopen_and_remove(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui.scheme_arm_assembly_dialog import PartDimensionsDialog, PlatePlacementDialog

    c = AppController()
    old = make_doc(c)
    source = tmp_path / 'old.kima'
    write_document(source, 'assembly', old, overwrite=False)
    original = source.read_bytes()
    d = SchemeArmAssemblyDialog(c, old, source)
    qtbot.addWidget(d)
    assert not d.remove_plate.isEnabled() and d.part_choice.count() == 4
    def add(dialog):
        assert not dialog.has_plate
        dialog.fields['width_mm'].setText('82.123456789')
        dialog.normal.setCurrentIndex(dialog.normal.findData('y'))
        dialog.offset_fields[0].setText('11')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PlatePlacementDialog, 'exec', add)
    d._edit_plate_placement()
    assert d.document['version'] == '0.16' and d.document['plate_placement'] == {'normal': 'y', 'offset_mm': [11, 0, 0]}
    assert d.remove_plate.isEnabled() and d.part_choice.count() == 5 and d.document != d._saved
    d.part_choice.setCurrentIndex(d.part_choice.findData('ball_plate'))
    assert '82.1235' in d.part_info.text()
    def edit(dialog):
        assert dialog.identifier == 'ball_plate'
        dialog.fields['thickness_mm'].setText('7')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PartDimensionsDialog, 'exec', edit)
    d._edit_selected_part()
    assert d.document['parts'][4]['geometry']['thickness_mm'] == 7
    part_path = tmp_path / 'plate.kim'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(part_path), ''))
    d._export_part()
    assert read_document(part_path, 'part') == d.document['parts'][4]
    p = c.project.front.hardpoints['lbj']
    c.move_point(p, (p.x + 10, p.y, p.z))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._apply_current_scheme()
    assert d.document['parts'][4]['geometry']['width_mm'] == 82.123456789
    assert d.document['plate_placement']['offset_mm'] == [11, 0, 0]
    output = tmp_path / 'new.kima'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(output), ''))
    d._save_copy()
    saved = read_document(output, 'assembly')
    assert saved == d.document and source.read_bytes() == original
    assert d.three_d.shutdown()
    d.close()
    reopened = SchemeArmAssemblyDialog(c, saved, output)
    qtbot.addWidget(reopened)
    assert reopened.part_choice.count() == 5 and reopened.remove_plate.isEnabled()
    def move(dialog):
        assert dialog.has_plate and not dialog.fields
        dialog.normal.setCurrentIndex(dialog.normal.findData('x'))
        dialog.offset_fields[2].setText('-12')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PlatePlacementDialog, 'exec', move)
    reopened._edit_plate_placement()
    assert reopened.document['plate_placement'] == {'normal': 'x', 'offset_mm': [11, 0, -12]}
    assert reopened.document['parts'][4] == saved['parts'][4]
    reopened._remove_plate()
    assert reopened.document['version'] == '0.15' and reopened.part_choice.count() == 4
    assert not reopened.remove_plate.isEnabled() and read_document(output, 'assembly') == saved
    reopened._saved = deepcopy(reopened.document)
    assert reopened.three_d.shutdown()
    reopened.close()


def test_plate_dialog_validation_and_modal_races(qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from suspensionlab.ui.scheme_arm_assembly_dialog import PlatePlacementDialog

    c = AppController()
    doc = make_doc(c)
    parent = QWidget()
    qtbot.addWidget(parent)
    form = PlatePlacementDialog(doc, parent)
    form.show()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    form.fields['hole_radius_mm'].setText('25')
    form.accept()
    assert warnings and form.isVisible()
    form.fields['hole_radius_mm'].setText('10')
    form.offset_fields[1].setText('nan')
    form.accept()
    assert len(warnings) == 2 and form.isVisible()
    form.offset_fields[1].setText('1,5')
    form.accept()
    assert not form.isVisible() and form.candidate()['plate_placement']['offset_mm'][1] == 1.5
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    def changed(form):
        d.axis.setCurrentIndex(d.axis.findData('z'))
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PlatePlacementDialog, 'exec', changed)
    d._edit_plate_placement()
    assert len(warnings) == 3 and d.document['version'] == '0.15' and d.document['axis'] == 'z'
    d._saved = deepcopy(d.document)
    assert d.three_d.shutdown()
    d.close()


def test_plate_import_and_confirmation_cancel_preserves_state(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.scheme_arm_assembly import make_plate, set_assembly_plate

    c = AppController()
    doc = set_assembly_plate(make_doc(c), make_plate(60, 50, 5, 10), {'normal': 'z', 'offset_mm': [0, 0, 0]})
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    d.part_choice.setCurrentIndex(d.part_choice.findData('ball_plate'))
    replacement = make_plate(90, 70, 8, 12)
    source = tmp_path / 'import.kim'
    write_document(source, 'part', replacement, overwrite=False)
    raw = source.read_bytes()
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(source), ''))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._import_selected_part()
    d._remove_plate()
    assert d.document == doc
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._import_selected_part()
    assert d.document['parts'][4] == replacement and d.document['plate_placement'] == doc['plate_placement']
    assert source.read_bytes() == raw
    d._saved = deepcopy(d.document)
    assert d.three_d.shutdown()
    d.close()


def test_menu_opens_plate_assembly(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.scheme_arm_assembly import make_plate, set_assembly_plate

    c = AppController()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    doc = set_assembly_plate(make_doc(c), make_plate(60, 50, 5, 10), {'normal': 'z', 'offset_mm': [0, 0, 0]})
    path = tmp_path / 'assembly.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    opened = []
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    def show(d):
        opened.append(deepcopy(d.document))
        assert d.three_d.shutdown()
        return 0
    monkeypatch.setattr(SchemeArmAssemblyDialog, 'exec', show)
    window.action_open_scheme_assembly.trigger()
    assert opened == [doc] and not c.dirty
    window.close()


def test_3d_selected_lower_arm_create_save_session_status_reopen(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui.controller import Selection

    c = AppController()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()
    view = window._vehicle_view
    window._tabs.setCurrentWidget(view)
    window._show_workspace()
    before = deepcopy(c.project.to_dict())
    assert not view.create_assembly_button.isEnabled()
    c.select(Selection('link', 'front', 'upper_arm'))
    assert not view.create_assembly_button.isEnabled()
    c.select(Selection('link', 'front', 'lower_arm'))
    assert view.create_assembly_button.isEnabled()
    output = tmp_path / 'левый рычаг.kima'
    monkeypatch.setattr(NewAssemblyParametersDialog, 'exec', lambda d: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(output), ''))
    opened = []
    def save_then_close(dialog):
        assert dialog.document['frame'] == 'vehicle_front_left_snapshot'
        assert 'ЛЕВЫЙ' in dialog.source_status.text()
        opened.append(deepcopy(dialog.document))
        if dialog.path is None:
            dialog._save_copy()
        assert dialog.three_d.shutdown()
        return 0
    monkeypatch.setattr(SchemeArmAssemblyDialog, 'exec', save_then_close)
    view.create_assembly_button.click()
    assert len(opened) == 1 and output.exists()
    assert view.session_assembly is not None and view.open_assembly_button.isEnabled()
    assert 'совпадают' in view.assembly_status.text() and 'сеанс' in view.assembly_status.text()
    assert c.project.to_dict() == before and not c.dirty
    initial = output.read_bytes()
    view.open_assembly_button.click()
    assert len(opened) == 2 and opened[1] == opened[0] and output.read_bytes() == initial
    point = c.project.front.hardpoints['lbj']
    c.move_point(point, (point.x, point.y, point.z + 10))
    assert 'ВНИМАНИЕ' in view.assembly_status.text() and output.read_bytes() == initial
    view.open_assembly_button.click()
    assert len(opened) == 3  # An outdated snapshot may be opened, never silently rebuilt.
    c.undo_last()
    assert 'совпадают' in view.assembly_status.text()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    output.write_text('changed outside', encoding='utf-8')
    view.open_assembly_button.click()
    assert warnings and len(opened) == 3 and output.read_text(encoding='utf-8') == 'changed outside'
    c.new_project('ring')
    assert view.session_assembly is None and not view.open_assembly_button.isEnabled()
    window.close()


def test_3d_creation_cancel_selection_and_project_races_do_not_create(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui.controller import Selection

    c = AppController()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    view = window._vehicle_view
    c.select(Selection('link', 'front', 'lower_arm'))
    warnings, opened = [], []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    monkeypatch.setattr(SchemeArmAssemblyDialog, 'exec', lambda d: opened.append(d))
    monkeypatch.setattr(NewAssemblyParametersDialog, 'exec', lambda d: QDialog.DialogCode.Rejected)
    window._new_selected_arm_assembly()
    assert not opened and not warnings and view.session_assembly is None
    def change_selection(d):
        c.select(Selection('link', 'front', 'upper_arm'))
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(NewAssemblyParametersDialog, 'exec', change_selection)
    window._new_selected_arm_assembly()
    assert warnings and not opened and view.session_assembly is None
    c.select(Selection('link', 'front', 'lower_arm'))
    def replace_project(d):
        c.new_project('ring')
        c.select(Selection('link', 'front', 'lower_arm'))
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(NewAssemblyParametersDialog, 'exec', replace_project)
    window._new_selected_arm_assembly()
    assert len(warnings) == 2 and not opened and view.session_assembly is None
    window.close()


def test_3d_creation_unsaved_does_not_claim_session_link(qtbot, tmp_path, monkeypatch):
    from suspensionlab.ui.controller import Selection

    c = AppController()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    c.select(Selection('link', 'front', 'lower_arm'))
    monkeypatch.setattr(NewAssemblyParametersDialog, 'exec', lambda d: QDialog.DialogCode.Accepted)
    def close_unsaved(d):
        assert d.path is None and d._saved is None
        assert d.three_d.shutdown()
        return 0
    monkeypatch.setattr(SchemeArmAssemblyDialog, 'exec', close_unsaved)
    window._new_selected_arm_assembly()
    assert window._vehicle_view.session_assembly is None
    assert not window._vehicle_view.open_assembly_button.isEnabled()
    window.close()


def test_3d_button_accepts_macpherson_and_rejects_other_roles(qtbot, tmp_path):
    from suspensionlab.model.templates import VehicleTemplateOptions, create_vehicle_template
    from suspensionlab.ui.controller import Selection

    c = AppController()
    window = MainWindow(c, QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    c.new_project(project=create_vehicle_template(VehicleTemplateOptions()))
    view = window._vehicle_view
    c.select(Selection('link', 'front', 'lower_arm'))
    assert view.create_assembly_button.isEnabled()
    c.select(Selection('link', 'rear', 'lower_arm'))
    assert not view.create_assembly_button.isEnabled()
    c.select(Selection('point', 'front', 'lbj'))
    assert not view.create_assembly_button.isEnabled()
    c.select(None)
    assert not view.create_assembly_button.isEnabled()
    window.close()


def test_background_views_discard_old_results_and_track_document(qtbot, monkeypatch):
    from threading import Event

    from suspensionlab.model.scheme_arm_assembly import set_assembly_axis
    from suspensionlab.ui import scheme_assembly_views

    entered, release = Event(), Event()
    calculate = scheme_assembly_views.assembly_views
    def slow(doc):
        entered.set()
        assert release.wait(5)
        return calculate(doc)
    monkeypatch.setattr(scheme_assembly_views, 'assembly_views', slow)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    d.views._timer.stop()
    d.views._start()
    assert entered.wait(3)
    try:
        d.document = set_assembly_axis(d.document, 'z')
        d._show_document()
        assert d.views.canvas.views is None and 'устарели' in d.views.status.text()
    finally:
        release.set()
    qtbot.waitUntil(lambda: d.views.canvas.views is not None, timeout=5000)
    assert d.views.canvas.views.axis == 'z' and 'Актуально' in d.views.status.text()
    assert 'Передняя труба' in d.views.dimensions.toPlainText()
    d.views.shutdown()
    assert d.three_d.shutdown()
    d._saved = deepcopy(d.document)
    d.close()


def test_views_shutdown_ignores_pending(qtbot):
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    d.views.shutdown()
    d.views._start()
    assert d.views._future is None and d.views._closed
    assert d.three_d.shutdown()
    d._saved = deepcopy(d.document)
    d.close()


def test_cad_projection_rejects_stale_results_and_can_close(qtbot, monkeypatch):
    from threading import Event

    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.model.scheme_arm_assembly import set_assembly_axis
    from suspensionlab.ui import cad_assembly_projection

    entered, released = Event(), Event()
    results = []
    class FakeJob:
        def run(self, doc):
            results.append(doc['axis'])
            if len(results) == 1:
                entered.set()
                assert released.wait(5)
            lines = (((0., 0., 1., 1.),),) * 3
            bounds = (0., 0., 0., 2., 3., 4.) if doc['axis'] == 'z' else (0., 0., 0., 9., 9., 9.)
            return CadAssemblyProjection(lines, bounds)
        def cancel(self):
            pass  # Simulate a response racing with cancellation.
    monkeypatch.setattr(cad_assembly_projection, 'CadAssemblyProjectionJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    monkeypatch.setattr(d, '_confirm_close', lambda: True)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    d.tabs.setCurrentWidget(view)
    d.show()
    assert not view.enable.isChecked() and view.canvas.projection is None
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    try:
        assert entered.wait(3)
        d.document = set_assembly_axis(d.document, 'z')
        d._saved = deepcopy(d.document)
        d._show_document()
        assert view.canvas.projection is None and not view.bounds.text() and 'очищены' in view.status.text()
    finally:
        released.set()
    qtbot.waitUntil(lambda: results == ['x', 'z'] and view.canvas.projection is not None, timeout=5000)
    assert 'Актуально' in view.status.text()
    assert 'X: 2.0' in view.bounds.text() and 'Y: 3.0' in view.bounds.text()
    assert 'Z: 4.0' in view.bounds.text() and 'не допуски' in view.bounds.text()
    assert view.show_dimensions.isChecked() and view.canvas.dimensions_enabled
    dimension_image = view.canvas.grab().toImage()
    assert not dimension_image.isNull()
    token, projection = view.generation, view.canvas.projection
    view.show_dimensions.setChecked(False)
    assert not view.canvas.dimensions_enabled and view.canvas.projection is projection
    assert view.generation == token and results == ['x', 'z']
    assert dimension_image != view.canvas.grab().toImage()
    view.show_dimensions.setChecked(True)
    assert view.canvas.dimensions_enabled and view.generation == token
    view.enable.setChecked(False)
    assert view.canvas.projection is None and not view.bounds.text() and 'Выключено' in view.status.text()
    d._saved = deepcopy(d.document)
    d.close()
    assert view._closed


def test_cad_projection_error_preserves_schematic_views(qtbot, monkeypatch):
    from suspensionlab.core.cad_transport import CadPreviewError
    from suspensionlab.ui import cad_assembly_projection

    class FakeJob:
        def run(self, _doc):
            raise CadPreviewError('missing_cad')
        def cancel(self):
            pass
    monkeypatch.setattr(cad_assembly_projection, 'CadAssemblyProjectionJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    monkeypatch.setattr(d, '_confirm_close', lambda: True)
    d._saved = deepcopy(d.document)
    d.cad_views.enable.setChecked(True)
    qtbot.waitUntil(lambda: 'CAD-ядро недоступно' in d.cad_views.status.text(), timeout=5000)
    qtbot.waitUntil(lambda: d.views.canvas.views is not None, timeout=5000)
    assert d.cad_views.retry.isEnabled() and d.cad_views.canvas.projection is None
    d._saved = deepcopy(d.document)
    d.close()


def test_cad_svg_export_current_snapshot_no_overwrite_and_toggle(qtbot, tmp_path, monkeypatch):
    from xml.etree import ElementTree as ET

    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint

    c = AppController()
    doc = make_doc(c)
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    assert not view.export_button.isEnabled()
    view.enable.setChecked(True)
    view._timer.stop()
    projection = CadAssemblyProjection((((0., 0., 1., 1.),),) * 3, (0., 0., 0., 2., 3., 4.))
    view._completed(view.generation, projection)
    assert view.export_button.isEnabled()
    view.show_dimensions.setChecked(False)
    target = tmp_path / 'виды.svg'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (str(target), ''))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    before_project = deepcopy(c.project.to_dict())
    view._export_svg()
    root = ET.fromstring(target.read_bytes())
    assert len(root.findall('.//{http://www.w3.org/2000/svg}path')) == 3
    assert 'НЕ ПРОИЗВОДСТВЕННЫЙ ЧЕРТЁЖ' in ' '.join(root.itertext())
    assert assembly_snapshot_fingerprint(doc) in view.snapshot_code.text()
    assert assembly_snapshot_fingerprint(doc) in ' '.join(root.itertext())
    assert 'Создан отдельный SVG' in view.export_status.text()
    content = target.read_bytes()
    view._export_svg()
    assert warnings and target.read_bytes() == content
    assert d.document == doc and c.project.to_dict() == before_project and not c.dirty
    d.close()


def test_cad_svg_export_refuses_document_change_during_dialog(qtbot, tmp_path, monkeypatch):
    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.model.scheme_arm_assembly import set_assembly_axis

    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    view.enable.setChecked(True)
    view._timer.stop()
    view._completed(view.generation, CadAssemblyProjection((((0., 0., 1., 1.),),) * 3,
                                                              (0., 0., 0., 2., 3., 4.)))
    target = tmp_path / 'race.svg'
    def choose(*args, **kwargs):
        # Simulates a modal race even before _show_document updates the view.
        d.document = set_assembly_axis(d.document, 'z')
        d._saved = deepcopy(d.document)
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    view._export_svg()
    assert warnings and not target.exists()
    d.close()


def test_cad_svg_export_refuses_dimension_toggle_during_dialog(qtbot, tmp_path, monkeypatch):
    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection

    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    view.enable.setChecked(True)
    view._timer.stop()
    view._completed(view.generation, CadAssemblyProjection((((0., 0., 1., 1.),),) * 3,
                                                              (0., 0., 0., 2., 3., 4.)))
    target = tmp_path / 'toggle.svg'
    def choose(*args, **kwargs):
        view.show_dimensions.setChecked(False)
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    view._export_svg()
    assert warnings and not target.exists()
    assert view.canvas.projection is not None  # Toggle is display-only.
    d.close()


def test_snapshot_code_updates_even_for_equal_boolean_and_number(qtbot):
    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint

    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    before = deepcopy(d.document)
    first = assembly_snapshot_fingerprint(before)
    assert first in view.snapshot_code.text() and 'Не хэш файла' in view.snapshot_code.text()
    view.enable.setChecked(True)
    view._timer.stop()
    view._completed(view.generation, CadAssemblyProjection((((0., 0., 1., 1.),),) * 3,
                                                              (0., 0., 0., 2., 3., 4.)))
    assert view.canvas.projection is not None
    old_generation = view.generation
    d.document['scheme']['front_axle']['arb']['enabled'] = 1
    d._saved = deepcopy(d.document)
    assert d.document == before  # Python compares True and 1 equal.
    d._show_document()
    changed = assembly_snapshot_fingerprint(d.document)
    assert changed != first and changed in view.snapshot_code.text()
    assert view.generation > old_generation and view.canvas.projection is None
    assert not view.export_button.isEnabled()
    d.close()


def test_material_estimate_follows_snapshot_without_saving_density(qtbot, tmp_path):
    from suspensionlab.model.assembly_material_estimate import assembly_part_volumes
    from suspensionlab.model.kim_format import read_document, write_document
    from suspensionlab.model.scheme_arm_assembly import edit_assembly_part, make_plate, set_assembly_plate

    c = AppController()
    initial = make_doc(c)
    d = SchemeArmAssemblyDialog(c, initial)
    qtbot.addWidget(d)
    d._saved = deepcopy(d.document)
    view = d.material_estimate
    assert view.density.text() == ''
    assert 'только объёмы' in view.status.text()
    assert 'tube_front' in view.result.toPlainText() and 'кг' not in view.result.toPlainText()
    view.density.setText('7850')
    assert 'Сумма условных масс' in view.result.toPlainText()
    total = sum(p.volume_mm3 for p in assembly_part_volumes(initial))
    assert f'{total * 7850 / 1e9:.3f} кг' in view.result.toPlainText()
    assert d.document == initial and not c.dirty
    view.density.setText('nan')
    assert not view.result.toPlainText() and 'Проверьте плотность' in view.status.text()
    view.density.setText('7,85e3')
    assert 'Сумма условных масс' in view.result.toPlainText()
    # The editor can change before a view refresh: do not calculate stale data.
    d.document = edit_assembly_part(d.document, 'housing_front',
                                     {'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 40})
    view.density.setText('7800')
    assert not view.result.toPlainText() and 'изменился' in view.status.text()
    d._show_document()
    assert view.density.text() == '7800' and 'Сумма условных масс' in view.result.toPlainText()
    d.document = set_assembly_plate(d.document, make_plate(60, 50, 5, 10),
                                     {'normal': 'z', 'offset_mm': [0, 0, 0]})
    d._show_document()
    assert 'ball_plate' in view.result.toPlainText()
    path = tmp_path / 'assembly.kima'
    write_document(path, 'assembly', d.document, overwrite=False)
    assert read_document(path, 'assembly') == d.document
    assert 'density' not in d.document
    d._saved = deepcopy(d.document)
    d.close()


def test_compare_and_copy_snapshot_code_without_cad(qtbot):
    from PySide6.QtWidgets import QApplication

    from suspensionlab.model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint

    c = AppController()
    doc = make_doc(c)
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    before = deepcopy(d.document)
    code = assembly_snapshot_fingerprint(doc)
    assert not view.enable.isChecked() and view.copy_code.isEnabled()
    view.copy_code.click()
    assert QApplication.clipboard().text() == code
    assert 'устареет' in view.comparison_status.text()
    view.comparison_input.setText('  ' + code.upper() + '  ')
    assert not view.comparison_status.text()
    view.compare_code.click()
    assert 'Коды совпадают' in view.comparison_status.text()
    assert 'не содержимое SVG' in view.comparison_status.text()
    other = ('0' if code[0] != '0' else '1') + code[1:]
    view.comparison_input.setText(other)
    assert not view.comparison_status.text()
    view.compare_code.click()
    assert 'Коды различаются' in view.comparison_status.text()
    for bad in ('', code[:63], code + '0', code[:10] + ' ' + code[10:], 'а' + code[1:]):
        view.comparison_input.setText(bad)
        view.compare_code.click()
        assert '64 шестнадцатеричных' in view.comparison_status.text()
    assert d.document == before and not c.dirty
    d.close()


def test_compare_snapshot_code_rejects_stale_document_and_clears_result(qtbot):
    from PySide6.QtWidgets import QApplication

    from suspensionlab.model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint

    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    original = deepcopy(d.document)
    code = assembly_snapshot_fingerprint(original)
    view.comparison_input.setText(code)
    view.compare_code.click()
    assert 'Коды совпадают' in view.comparison_status.text()
    # Even if Python treats True and 1 as equal, the current-document guard
    # rejects a changed fingerprint before the widgets are refreshed.
    d.document['scheme']['front_axle']['arb']['enabled'] = 1
    assert d.document == original
    view.compare_code.click()
    assert 'изменился' in view.comparison_status.text()
    QApplication.clipboard().setText('unchanged')
    view.copy_code.click()
    assert QApplication.clipboard().text() == 'unchanged'
    d._saved = deepcopy(d.document)
    d._show_document()
    assert not view.comparison_status.text()
    view.compare_code.click()
    assert 'Коды различаются' in view.comparison_status.text()
    view.copy_code.click()
    assert QApplication.clipboard().text() == assembly_snapshot_fingerprint(d.document)
    d.close()
    view._compare_snapshot_code()
    assert 'недоступен' in view.comparison_status.text()


def test_export_refuses_equal_but_differently_fingerprinted_snapshot(qtbot, tmp_path, monkeypatch):
    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection

    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    view.enable.setChecked(True)
    view._timer.stop()
    view._completed(view.generation, CadAssemblyProjection((((0., 0., 1., 1.),),) * 3,
                                                              (0., 0., 0., 2., 3., 4.)))
    before = deepcopy(d.document)
    target = tmp_path / 'boolean-race.svg'
    def choose(*args, **kwargs):
        d.document['scheme']['front_axle']['arb']['enabled'] = 1
        d._saved = deepcopy(d.document)
        assert before == d.document
        return str(target), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', choose)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    view._export_svg()
    assert warnings and not target.exists()
    d.close()


def test_delayed_projection_rejected_when_snapshot_changes_without_refresh(qtbot):
    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection

    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    view.enable.setChecked(True)
    view._timer.stop()
    token = view.generation
    d.document['scheme']['front_axle']['arb']['enabled'] = 1
    d._saved = deepcopy(d.document)
    view._completed(token, CadAssemblyProjection((((0., 0., 1., 1.),),) * 3,
                                                   (0., 0., 0., 2., 3., 4.)))
    assert view.canvas.projection is None and not view.export_button.isEnabled()
    assert 'снимок изменился' in view.status.text()
    d.close()


def test_tube_notch_preview_stale_result_selection_and_shutdown(qtbot, monkeypatch):
    from threading import Event

    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.core.cad_tube_notch_job import TubeNotchPreview
    from suspensionlab.ui import tube_notch_preview

    entered, release = Event(), Event()
    calls = []
    lines = (((0., 0., 1., 1.),),) * 3
    projection = CadAssemblyProjection(lines, (0., 0., 0., 2., 3., 4.))
    result = TubeNotchPreview(projection, projection, projection, projection)

    class FakeJob:
        def run(self, doc, tube, housing):
            calls.append((tube, housing))
            if len(calls) == 1:
                entered.set()
                assert release.wait(5)
            return result
        def cancel(self):
            pass  # Force the first reply to arrive after selection changed.

    monkeypatch.setattr(tube_notch_preview, 'TubeNotchPreviewJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    monkeypatch.setattr(d, '_confirm_close', lambda: True)
    view = d.notch_preview
    d.tabs.setCurrentWidget(view)
    d.show()
    assert not view.enable.isChecked() and view.canvas.result is None
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    try:
        assert entered.wait(3)
        generation = view.generation
        view.only_tube.setChecked(True)
        assert view.generation == generation and view.canvas.tube_only
        view.tube.setCurrentIndex(1)
        view.housing.setCurrentIndex(1)
        assert view.canvas.result is None
    finally:
        release.set()
    qtbot.waitUntil(lambda: len(calls) == 2 and view.canvas.result is result, timeout=5000)
    assert calls == [('tube_front', 'housing_front'), ('tube_rear', 'housing_rear')]
    generation = view.generation
    view.plane.setCurrentIndex(1)
    assert view.canvas.plane == 'XZ' and view.generation == generation and view.canvas.result is result
    assert not view.canvas.grab().toImage().isNull()
    view.enable.setChecked(False)
    assert view.canvas.result is None and 'Выключено' in view.status.text()
    d._saved = deepcopy(d.document)
    d.close()
    assert view._closed and view.shutdown()


def test_tube_notch_preview_failure_does_not_modify_assembly(qtbot, monkeypatch):
    from suspensionlab.core.cad_transport import CadPreviewError
    from suspensionlab.ui import tube_notch_preview

    class FakeJob:
        def run(self, doc, tube, housing):
            raise CadPreviewError('no_overlap')
        def cancel(self):
            pass

    monkeypatch.setattr(tube_notch_preview, 'TubeNotchPreviewJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    original = deepcopy(d.document)
    view = d.notch_preview
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    qtbot.waitUntil(lambda: 'не пересекаются' in view.status.text(), timeout=5000)
    assert view.canvas.result is None and view.retry.isEnabled() and d.document == original
    d._saved = deepcopy(d.document)
    d.close()
    assert view._closed


def test_tube_notch_plate_selection_and_removal_clears_stale_result(qtbot, monkeypatch):
    from threading import Event

    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.core.cad_transport import CadPreviewError
    from suspensionlab.core.cad_tube_notch_job import TubeNotchPreview
    from suspensionlab.model.scheme_arm_assembly import make_plate, set_assembly_plate
    from suspensionlab.ui import tube_notch_preview

    entered, release = Event(), Event()
    calls = []
    lines = (((0., 0., 1., 1.),),) * 3
    projection = CadAssemblyProjection(lines, (0., 0., 0., 2., 3., 4.))
    result = TubeNotchPreview(projection, projection, projection, projection)

    class FakeJob:
        def run(self, doc, tube, cutter):
            calls.append((doc['version'], tube, cutter))
            if len(calls) == 1:
                entered.set()
                assert release.wait(5)
            if doc['version'] != '0.16':
                raise CadPreviewError('missing_plate')
            return result
        def cancel(self):
            pass

    monkeypatch.setattr(tube_notch_preview, 'TubeNotchPreviewJob', FakeJob)
    c = AppController()
    doc = set_assembly_plate(make_doc(c), make_plate(60, 60, 5, 9),
                             {'normal': 'y', 'offset_mm': [0, 0, 0]})
    d = SchemeArmAssemblyDialog(c, doc)
    qtbot.addWidget(d)
    monkeypatch.setattr(d, '_confirm_close', lambda: True)
    view = d.notch_preview
    view.housing.setCurrentIndex(view.housing.findData('ball_plate'))
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    try:
        assert entered.wait(3)
        d.document = set_assembly_plate(d.document, None)
        d._show_document()
        assert view.canvas.result is None
    finally:
        release.set()
    qtbot.waitUntil(lambda: 'пластина не добавлена' in view.status.text(), timeout=5000)
    assert view.canvas.result is None and view.retry.isEnabled()
    assert calls == [('0.16', 'tube_front', 'ball_plate'), ('0.15', 'tube_front', 'ball_plate')]
    d.document = doc
    d._show_document()
    qtbot.waitUntil(lambda: view.canvas.result is result, timeout=5000)
    assert 'изменений не видно' in view.status.text()
    assert d.document == doc
    d._saved = deepcopy(d.document)
    d.close()
    assert view._closed


def test_tube_to_tube_selection_prevents_self_cut_and_ignores_old_result(qtbot, monkeypatch):
    from threading import Event

    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.core.cad_tube_notch_job import TubeNotchPreview
    from suspensionlab.ui import tube_notch_preview

    entered, release = Event(), Event()
    calls = []
    projection = CadAssemblyProjection((((0., 0., 1., 1.),),) * 3, (0., 0., 0., 2., 3., 4.))
    result = TubeNotchPreview(projection, projection, projection, projection)

    class FakeJob:
        def run(self, doc, tube, cutter):
            calls.append((tube, cutter))
            if len(calls) == 1:
                entered.set()
                assert release.wait(5)
            return result
        def cancel(self):
            pass

    monkeypatch.setattr(tube_notch_preview, 'TubeNotchPreviewJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    monkeypatch.setattr(d, '_confirm_close', lambda: True)
    original = deepcopy(d.document)
    view = d.notch_preview
    view.housing.setCurrentIndex(view.housing.findData('tube_rear'))
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    try:
        assert entered.wait(3)
        view.tube.setCurrentIndex(view.tube.findData('tube_rear'))
        assert view.canvas.result is None and 'самой собой' in view.status.text()
        assert view._pending is None and not view.retry.isEnabled()
    finally:
        release.set()
    qtbot.waitUntil(lambda: view._worker is None, timeout=5000)
    assert view.canvas.result is None and calls == [('tube_front', 'tube_rear')]
    view.housing.setCurrentIndex(view.housing.findData('tube_front'))
    qtbot.waitUntil(lambda: view.canvas.result is result, timeout=5000)
    assert calls == [('tube_front', 'tube_rear'), ('tube_rear', 'tube_front')]
    assert d.document == original
    d._saved = deepcopy(d.document)
    d.close()
    assert view._closed


def test_notch_only_tube_mode_switches_without_recalculation(qtbot, monkeypatch):
    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.core.cad_tube_notch_job import TubeNotchPreview
    from suspensionlab.ui import tube_notch_preview

    lines = (((0., 0., 1., 1.),),) * 3
    different = (((0., 1., 1., 0.),),) * 3
    bounds = (0., 0., 0., 2., 3., 4.)
    pair = CadAssemblyProjection(lines, bounds)
    tube_before = CadAssemblyProjection(lines, bounds)
    tube_after = CadAssemblyProjection(different, bounds)
    result = TubeNotchPreview(pair, pair, tube_before, tube_after)
    calls = []

    class FakeJob:
        def run(self, doc, tube, cutter):
            calls.append((tube, cutter))
            return result
        def cancel(self):
            pass

    monkeypatch.setattr(tube_notch_preview, 'TubeNotchPreviewJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    monkeypatch.setattr(d, '_confirm_close', lambda: True)
    view = d.notch_preview
    d.tabs.setCurrentWidget(view)
    d.show()
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    qtbot.waitUntil(lambda: view.canvas.result is result, timeout=5000)
    assert 'пара деталей' in view.status.text() and 'изменений не видно' in view.status.text()
    pair_image = view.canvas.grab().toImage()
    generation = view.generation
    view.only_tube.setChecked(True)
    assert view.canvas.tube_only and 'режущая деталь скрыта' in view.status.text()
    assert 'изменений не видно' not in view.status.text()
    assert view.generation == generation and calls == [('tube_front', 'housing_front')]
    assert view.canvas.grab().toImage() != pair_image
    view.plane.setCurrentIndex(1)
    assert view.canvas.plane == 'XZ' and view.generation == generation
    view.only_tube.setChecked(False)
    assert not view.canvas.tube_only and view.generation == generation
    assert view.canvas.result is result and calls == [('tube_front', 'housing_front')]
    view.enable.setChecked(False)
    assert view.canvas.result is None
    d._saved = deepcopy(d.document)
    d.close()
    assert view._closed


def test_notch_sequence_order_changes_invalidate_stale_results(qtbot, monkeypatch):
    from threading import Event

    from PySide6.QtCore import Qt

    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.core.cad_tube_notch_sequence_job import SequencePreview, SequenceStagePreview
    from suspensionlab.ui import tube_notch_sequence_preview

    entered, release = Event(), Event()
    calls = []
    lines = (((0., 0., 1., 1.),),) * 3
    class FakeJob:
        def run(self, doc, tube, cutters):
            calls.append((tube, cutters))
            if len(calls) == 1:
                entered.set()
                assert release.wait(5)
            bounds = (0., 0., 0., 2., 3., 4.) if cutters[0] == 'tube_rear' else (0., 0., 0., 9., 9., 9.)
            before = CadAssemblyProjection(lines, bounds)
            return SequencePreview(before, tuple(SequenceStagePreview(c, before, before, before) for c in cutters))
        def cancel(self):
            pass  # Force an obsolete reply after cancellation.

    monkeypatch.setattr(tube_notch_sequence_preview, 'SequencePreviewJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    monkeypatch.setattr(d, '_confirm_close', lambda: True)
    view = d.notch_sequence
    d.tabs.setCurrentWidget(view)
    d.show()
    view.cutters.item(0).setCheckState(Qt.CheckState.Checked)  # front housing
    view.cutters.item(4).setCheckState(Qt.CheckState.Checked)  # rear tube
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    try:
        assert entered.wait(3)
        view.cutters.setCurrentRow(4)
        for _ in range(4):
            view.up.click()
        assert view._order() == ('tube_rear', 'housing_front') and view.canvas.result is None
    finally:
        release.set()
    qtbot.waitUntil(lambda: len(calls) == 2 and view.canvas.result is not None, timeout=5000)
    assert calls == [('tube_front', ('housing_front', 'tube_rear')),
                     ('tube_front', ('tube_rear', 'housing_front'))]
    assert view.canvas.result.before.bounds_mm == (0., 0., 0., 2., 3., 4.)
    assert 'только выбранная труба' in view.status.text()
    generation = view.generation
    view.plane.setCurrentIndex(1)
    assert view.canvas.plane == 'XZ' and view.generation == generation
    assert not view.canvas.grab().toImage().isNull()
    view.enable.setChecked(False)
    assert view.canvas.result is None and 'Выключено' in view.status.text()
    d._saved = deepcopy(d.document)
    d.close()
    assert view._closed


def test_notch_sequence_reports_failing_step_and_never_shows_partial(qtbot, monkeypatch):
    from PySide6.QtCore import Qt

    from suspensionlab.core.cad_tube_notch_sequence_job import SequencePreviewError
    from suspensionlab.ui import tube_notch_sequence_preview

    class FakeJob:
        def run(self, doc, tube, cutters):
            raise SequencePreviewError('no_overlap', 1, cutters[1])
        def cancel(self):
            pass
    monkeypatch.setattr(tube_notch_sequence_preview, 'SequencePreviewJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    view = d.notch_sequence
    original = deepcopy(d.document)
    view.cutters.item(0).setCheckState(Qt.CheckState.Checked)
    view.cutters.item(1).setCheckState(Qt.CheckState.Checked)
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    qtbot.waitUntil(lambda: 'Шаг 2' in view.status.text(), timeout=5000)
    assert 'Задний корпус' in view.status.text() and 'пересечения' in view.status.text()
    assert 'Частичный результат не показан' in view.status.text() and view.canvas.result is None
    assert view.retry.isEnabled() and d.document == original
    d._saved = deepcopy(d.document)
    d.close()
    assert view._closed


def test_notch_sequence_rejects_snapshot_changed_without_refresh(qtbot):
    from PySide6.QtCore import Qt

    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.core.cad_tube_notch_sequence_job import SequencePreview, SequenceStagePreview

    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    view = d.notch_sequence
    view.cutters.item(0).setCheckState(Qt.CheckState.Checked)
    view.enable.setChecked(True)
    view._timer.stop()
    token = view.generation
    d.document['scheme']['front_axle']['arb']['enabled'] = 1
    p = CadAssemblyProjection((((0., 0., 1., 1.),),) * 3, (0., 0., 0., 2., 3., 4.))
    view._completed(token, SequencePreview(p, (SequenceStagePreview('housing_front', p, p, p),)))
    assert view.canvas.result is None and 'снимок изменился' in view.status.text()
    d._saved = deepcopy(d.document)
    d.close()
    assert view._closed


def test_notch_sequence_shutdown_cancels_running_worker(qtbot, monkeypatch):
    from threading import Event

    from PySide6.QtCore import Qt

    from suspensionlab.core.cad_transport import CadPreviewError
    from suspensionlab.ui import tube_notch_sequence_preview

    entered, stopped = Event(), Event()
    class FakeJob:
        def run(self, doc, tube, cutters):
            entered.set()
            assert stopped.wait(5)
            raise CadPreviewError('cancelled')
        def cancel(self):
            stopped.set()
    monkeypatch.setattr(tube_notch_sequence_preview, 'SequencePreviewJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    view = d.notch_sequence
    view.cutters.item(0).setCheckState(Qt.CheckState.Checked)
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    try:
        assert entered.wait(3)
        d._saved = deepcopy(d.document)
        d.close()
        assert view._closed and stopped.is_set()
    finally:
        stopped.set()
        view.shutdown()


def test_notch_sequence_switches_stages_without_new_calculation(qtbot, monkeypatch):
    from PySide6.QtCore import Qt

    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.core.cad_tube_notch_sequence_job import SequencePreview, SequenceStagePreview
    from suspensionlab.ui import tube_notch_sequence_preview

    calls = []
    bounds = (0., 0., 0., 2., 3., 4.)
    before = CadAssemblyProjection((((0., 0., 1., 1.),),) * 3, bounds)
    first = CadAssemblyProjection((((0., 1., 1., 0.),),) * 3, bounds)
    final = CadAssemblyProjection((((0., 0., 1., 0.),),) * 3, bounds)
    class FakeJob:
        def run(self, doc, tube, cutters):
            calls.append((tube, cutters))
            return SequencePreview(before, (SequenceStagePreview(cutters[0], first, before, first),
                                            SequenceStagePreview(cutters[1], final, first, final)))
        def cancel(self):
            pass

    monkeypatch.setattr(tube_notch_sequence_preview, 'SequencePreviewJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    monkeypatch.setattr(d, '_confirm_close', lambda: True)
    view = d.notch_sequence
    d.tabs.setCurrentWidget(view)
    d.show()
    view.cutters.item(0).setCheckState(Qt.CheckState.Checked)
    view.cutters.item(4).setCheckState(Qt.CheckState.Checked)
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    qtbot.waitUntil(lambda: view.canvas.result is not None, timeout=5000)
    assert view.stage.isEnabled() and view.stage.count() == 2 and view.stage.currentIndex() == 1
    assert 'итог' in view.stage.currentText() and 'шага 2 из 2' in view.status.text()
    assert view.canvas.result.after is final and view.canvas.after_title == 'Шаг 2'
    final_image = view.canvas.grab().toImage()
    generation = view.generation
    view.stage.setCurrentIndex(0)
    assert view.canvas.result.before is before and view.canvas.result.after is first
    assert view.canvas.after_title == 'Шаг 1' and 'шага 1 из 2' in view.status.text()
    assert 'Передний корпус' in view.status.text()
    assert view.generation == generation and calls == [('tube_front', ('housing_front', 'tube_rear'))]
    assert view.canvas.grab().toImage() != final_image
    view.show_pair.setChecked(True)
    assert not view.canvas.tube_only and view.canvas.before_title == 'До 1' and view.canvas.after_title == 'После 1'
    assert view.canvas.result.before is before and view.canvas.result.after is first
    assert 'непосредственно до и после шага 1' in view.status.text()
    view.stage.setCurrentIndex(1)
    assert view.canvas.result.before is first and view.canvas.result.after is final
    assert 'предыдущие резы уже учтены' in view.status.text()
    assert view.canvas.before_title == 'До 2' and view.canvas.after_title == 'После 2'
    assert view.generation == generation and len(calls) == 1
    view.show_pair.setChecked(False)
    assert view.canvas.tube_only and view.canvas.result.tube_before is before
    assert view.canvas.result.tube_after is final and view.canvas.before_title == 'Исходная'
    view.plane.setCurrentIndex(1)
    assert view.generation == generation and view.canvas.plane == 'XZ'
    view.enable.setChecked(False)
    assert view.canvas.result is None and view.stage.count() == 0 and not view.stage.isEnabled()
    d._saved = deepcopy(d.document)
    d.close()


@pytest.mark.parametrize("action", ["stage", "pair", "plane"])
def test_notch_sequence_stage_change_rejects_silently_changed_snapshot(qtbot, monkeypatch, action):
    from PySide6.QtCore import Qt

    from suspensionlab.core.cad_assembly_projection_job import CadAssemblyProjection
    from suspensionlab.core.cad_tube_notch_sequence_job import SequencePreview, SequenceStagePreview
    from suspensionlab.ui import tube_notch_sequence_preview

    p = CadAssemblyProjection((((0., 0., 1., 1.),),) * 3, (0., 0., 0., 2., 3., 4.))
    class FakeJob:
        def run(self, doc, tube, cutters):
            return SequencePreview(p, tuple(SequenceStagePreview(c, p, p, p) for c in cutters))
        def cancel(self):
            pass
    monkeypatch.setattr(tube_notch_sequence_preview, 'SequencePreviewJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    view = d.notch_sequence
    view.cutters.item(0).setCheckState(Qt.CheckState.Checked)
    view.cutters.item(4).setCheckState(Qt.CheckState.Checked)
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    qtbot.waitUntil(lambda: view.canvas.result is not None, timeout=5000)
    d.document['scheme']['front_axle']['arb']['enabled'] = 1
    if action == 'stage':
        view.stage.setCurrentIndex(0)
    elif action == 'pair':
        view.show_pair.setChecked(True)
    else:
        view.plane.setCurrentIndex(1)
    assert view.canvas.result is None and 'снимок изменился' in view.status.text()
    assert view.stage.count() == 0 and not view.stage.isEnabled()
    d._saved = deepcopy(d.document)
    d.close()
