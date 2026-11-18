"""Сборка рычага из отдельных файлов: создание, открытие, безопасность."""
from copy import deepcopy

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
            return CadAssemblyProjection(lines)
        def cancel(self):
            pass  # Simulate a response racing with cancellation.
    monkeypatch.setattr(cad_assembly_projection, 'CadAssemblyProjectionJob', FakeJob)
    c = AppController()
    d = SchemeArmAssemblyDialog(c, make_doc(c))
    qtbot.addWidget(d)
    monkeypatch.setattr(d, '_confirm_close', lambda: True)
    d._saved = deepcopy(d.document)
    view = d.cad_views
    assert not view.enable.isChecked() and view.canvas.projection is None
    view.enable.setChecked(True)
    view._timer.stop()
    view._start()
    try:
        assert entered.wait(3)
        d.document = set_assembly_axis(d.document, 'z')
        d._saved = deepcopy(d.document)
        d._show_document()
        assert view.canvas.projection is None and 'очищены' in view.status.text()
    finally:
        released.set()
    qtbot.waitUntil(lambda: results == ['x', 'z'] and view.canvas.projection is not None, timeout=5000)
    assert 'Актуально' in view.status.text()
    view.enable.setChecked(False)
    assert view.canvas.projection is None and 'Выключено' in view.status.text()
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
