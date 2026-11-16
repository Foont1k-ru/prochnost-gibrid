import csv
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from suspensionlab.model.units import UnitSettings
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.point_table_dialog import PointTableDialog


def row_for(dialog, role, code):
    return dialog._rows.index((role, code))


def test_atomic_edit_undo_redo_and_precision(qtbot):
    controller = AppController()
    a = controller.project.front.hardpoints['spring_lo']
    b = controller.project.rear.hardpoints['spring_up']
    a.x = 0.12345678901234
    before_a, before_b = a.as_tuple(), b.as_tuple()
    dialog = PointTableDialog(controller)
    qtbot.addWidget(dialog)
    ra, rb = row_for(dialog, 'front', 'spring_lo'), row_for(dialog, 'rear', 'spring_up')
    dialog._table.item(ra, 5).setText('2 см')
    dialog._table.item(rb, 6).setText('2 * 10')
    dialog._apply_changes()
    assert a.as_tuple() == (before_a[0], 20, before_a[2])
    assert b.z == 20
    assert controller.undo.depth() == 1 and controller.dirty
    controller.undo_last()
    assert a.as_tuple() == before_a and b.as_tuple() == before_b
    controller.redo_last()
    assert a.y == 20 and b.z == 20


def test_invalid_is_atomic_and_reveals_hidden_row(qtbot):
    c = AppController()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    f, r = row_for(d, 'front', 'spring_lo'), row_for(d, 'rear', 'spring_up')
    old = c.project.front.hardpoints['spring_lo'].as_tuple()
    d._table.item(f, 4).setText('12')
    d._table.item(r, 6).setText('1e309')
    d._filter.setCurrentIndex(1)
    d._apply_changes()
    assert c.project.front.hardpoints['spring_lo'].as_tuple() == old
    assert c.undo.depth() == 0 and not c.dirty
    assert d._filter.currentData() == 'all' and d._table.currentRow() == r
    d._table.item(r, 6).setText('25')
    d._apply_changes()
    assert c.undo.depth() == 1


def test_locks_checked_in_ui_and_controller_atomically(qtbot):
    c = AppController()
    c.project.front.hardpoints['spring_lo'].locked = True
    c.set_lock('rear.point.spring_up.z', True)
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    f, r = row_for(d, 'front', 'spring_lo'), row_for(d, 'rear', 'spring_up')
    assert not d._table.item(f, 4).flags() & Qt.ItemFlag.ItemIsEditable
    assert not d._table.item(r, 6).flags() & Qt.ItemFlag.ItemIsEditable
    a = c.project.front.hardpoints['spring_up']
    before = a.as_tuple()
    with pytest.raises(ValueError):
        c.move_points({('front', 'spring_up'): (1, 2, 3), ('rear', 'spring_up'): (1, 2, 3)})
    assert a.as_tuple() == before


def test_csv_is_complete_model_not_draft_and_units(qtbot, tmp_path):
    c = AppController()
    c.set_units(UnitSettings(length='in'))
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    row = row_for(d, 'front', 'spring_lo')
    point = c.project.front.hardpoints['spring_lo']
    before = point.x
    d._table.item(row, 4).setText('1')
    d._filter.setCurrentIndex(2)
    path = tmp_path / 'points.csv'
    d.export_csv(path)
    with path.open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    result = next(r for r in rows if r['axle'] == 'front' and r['code'] == 'spring_lo')
    assert float(result['x_mm']) == before and result['representation'] == 'mirrored'
    assert len(rows) == len(d._rows)
    d._apply_changes()
    assert point.x == 25.4


def test_stale_and_discard(qtbot, monkeypatch):
    c = AppController()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    d.show()
    d._table.item(0, 4).setText('3')
    c.set_units(UnitSettings(length='cm'))
    assert d._stale and not d._apply.isEnabled() and not d._export.isEnabled()
    with pytest.raises(ValueError):
        d.export_csv(Path('unwanted.csv'))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d.reject()
    assert d.isVisible()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d.reject()
    assert not d.isVisible()


def test_explicit_and_single_representation(qtbot, tmp_path):
    c = AppController()
    c.set_axle_type('rear', 'live_axle_coil')
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    assert d._table.item(row_for(d, 'rear', 'spring_lo_l'), 3).text() != d._table.item(
        row_for(d, 'rear', 'differential_center'), 3).text()


def test_project_change_invalidates_draft(qtbot):
    c = AppController()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    d._table.item(0, 4).setText('123')
    c.new_project()
    d._apply_changes()
    assert d._stale and c.undo.depth() == 0 and not c.dirty


def test_repeated_apply_is_separate_undo_and_noop(qtbot):
    c = AppController()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    row = row_for(d, 'front', 'spring_lo')
    point = c.project.front.hardpoints['spring_lo']
    before = point.x
    d._apply_changes()
    assert c.undo.depth() == 0
    d._table.item(row, 4).setText('12')
    d._apply_changes()
    d._table.item(row, 4).setText('13')
    d._apply_changes()
    assert c.undo.depth() == 2
    c.undo_last()
    assert point.x == 12
    c.undo_last()
    assert point.x == before


def test_user_editor_then_apply_and_close_confirmation(qtbot, monkeypatch):
    from PySide6.QtWidgets import QLineEdit

    c = AppController()
    d = PointTableDialog(c)
    qtbot.addWidget(d)
    d.show()
    row = row_for(d, 'front', 'spring_lo')
    d._table.setCurrentCell(row, 4)
    d._table.editItem(d._table.item(row, 4))
    editor = d._table.findChild(QLineEdit)
    assert editor is not None
    editor.selectAll()
    qtbot.keyClicks(editor, '42')
    qtbot.mouseClick(d._apply, Qt.MouseButton.LeftButton)
    assert c.project.front.hardpoints['spring_lo'].x == 42
    d._table.item(row, 4).setText('99')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    d.close()
    assert d.isVisible()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    d.close()
    assert not d.isVisible() and c.project.front.hardpoints['spring_lo'].x == 42
