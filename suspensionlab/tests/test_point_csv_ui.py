import csv

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from suspensionlab.model.units import UnitSettings
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.point_import_dialog import PointImportDialog
from suspensionlab.ui.point_table_dialog import PointTableDialog


def edited_file(dialog, path, changes):
    dialog.export_csv(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream))
    for role, code, column, text in changes:
        row = next(r for r in rows[1:] if r[0] == role and r[2] == code)
        row[column] = text
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        csv.writer(stream).writerows(rows)


def test_import_preview_apply_units_filter_undo_redo(qtbot, tmp_path):
    c = AppController()
    c.set_units(UnitSettings(length='in'))
    a = c.project.front.hardpoints['spring_lo']
    b = c.project.rear.hardpoints['spring_up']
    a.x = 0.123456789012345
    a.zone_min, a.zone_max = (-10, 500, 100), (10, 530, 160)
    old_a, old_b = a.as_tuple(), b.as_tuple()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    d.show()
    d._filter.setCurrentIndex(2)
    path = tmp_path / 'points.csv'
    edited_file(d, path, [('front', 'spring_lo', 5, '12.3456789012345'),
                          ('rear', 'spring_up', 7, '-25.4')])
    seen = []
    def confirm():
        preview = d.findChild(PointImportDialog)
        seen.append((preview._table.rowCount(), preview._table.item(0, 4).text(),
                     preview._table.item(0, 5).text(), preview._table.item(0, 6).text(),
                     preview._apply.isEnabled(), c.undo.depth()))
        preview._apply.click()
    QTimer.singleShot(0, confirm)
    d.import_csv(path)
    assert seen == [(2, repr(old_a[0]), '12.3456789012345', 'Вне зоны', True, 0)]
    assert a.x == 12.3456789012345 and b.z == -25.4
    assert c.undo.depth() == 1 and c.dirty and d._filter.currentData() == 'rear'
    assert c.issues and any(i.key == 'diag.point_out_of_zone' and i.code == 'spring_lo' for i in c.issues)
    c.undo_last()
    assert a.as_tuple() == old_a and b.as_tuple() == old_b
    c.redo_last()
    assert a.x == 12.3456789012345 and b.z == -25.4


def test_cancel_and_unchanged_file_do_not_modify_project(qtbot, tmp_path):
    c = AppController()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    path = tmp_path / 'points.csv'
    edited_file(d, path, [('front', 'spring_lo', 5, '44')])
    QTimer.singleShot(0, lambda: d.findChild(PointImportDialog).reject())
    d.import_csv(path)
    assert c.project.front.hardpoints['spring_lo'].x == 0 and c.undo.depth() == 0 and not c.dirty
    d.export_csv(path)
    seen = []
    def inspect():
        preview = [v for v in d.findChildren(PointImportDialog) if v.isVisible()][0]
        seen.append((preview._table.rowCount(), preview._apply.isEnabled()))
        preview.reject()
    QTimer.singleShot(0, inspect)
    d.import_csv(path)
    assert seen == [(0, False)] and c.undo.depth() == 0


def test_draft_block_reset_and_failed_import_preserves_draft(qtbot, tmp_path, monkeypatch):
    c = AppController()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    path = tmp_path / 'points.csv'
    d.export_csv(path)
    d._table.item(0, 4).setText('99')
    d.import_csv(path)
    assert d._table.item(0, 4).text() == '99' and d._changed and c.undo.depth() == 0
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d._reset_draft()
    assert d._changed
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d._reset_draft()
    assert not d._changed and c.undo.depth() == 0
    path.write_text('invalid', encoding='utf-8')
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d.import_csv(path)
    assert warnings and c.undo.depth() == 0 and not c.dirty


def test_model_changed_while_preview_open_cannot_import(qtbot, tmp_path):
    c = AppController()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    path = tmp_path / 'points.csv'
    edited_file(d, path, [('front', 'spring_lo', 5, '40')])
    observed = []
    def change_model():
        preview = d.findChild(PointImportDialog)
        c.set_units(UnitSettings(length='cm'))
        observed.append(preview._apply.isEnabled())
        preview.accept()  # Даже программное подтверждение не обходит проверку устаревания.
    QTimer.singleShot(0, change_model)
    d.import_csv(path)
    assert observed == [False] and d._stale and not d._import.isEnabled()
    assert c.project.front.hardpoints['spring_lo'].x == 0 and c.undo.depth() == 0


def test_unannounced_model_change_rechecked_before_apply(qtbot, tmp_path):
    c = AppController()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    path = tmp_path / 'points.csv'
    edited_file(d, path, [('front', 'spring_lo', 5, '40')])
    def change_model():
        c.project.front.hardpoints['spring_up'].z += 1  # обходим контроллер намеренно
        d.findChild(PointImportDialog).accept()
    QTimer.singleShot(0, change_model)
    d.import_csv(path)
    assert d._stale and c.undo.depth() == 0 and c.project.front.hardpoints['spring_lo'].x == 0


def test_export_cannot_overwrite_project_or_symlink(qtbot, tmp_path, monkeypatch):
    c = AppController()
    project_path = c.save_project(tmp_path / 'project.susp.json')
    original = project_path.read_bytes()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    with pytest.raises(ValueError):
        d.export_csv(project_path)
    alias = tmp_path / 'link.csv'
    try:
        alias.symlink_to(project_path)
    except OSError:
        pass
    else:
        with pytest.raises(ValueError):
            d.export_csv(alias)
    assert project_path.read_bytes() == original
    autosave = tmp_path / 'autosave.susp.json'
    autosave.write_bytes(b'backup')
    monkeypatch.setattr('suspensionlab.ui.point_table_dialog.autosave_path', lambda: autosave)
    with pytest.raises(ValueError):
        d.export_csv(autosave)
    assert autosave.read_bytes() == b'backup'
