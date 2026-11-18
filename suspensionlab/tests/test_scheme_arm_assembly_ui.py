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
