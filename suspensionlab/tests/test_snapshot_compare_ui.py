import copy
import csv

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from suspensionlab.model.entities import Hardpoint, Snapshot
from suspensionlab.ui.controller import AppController, Selection
from suspensionlab.ui.main_window import MainWindow
from suspensionlab.ui.snapshot_compare_dialog import SnapshotCompareDialog


def setup_comparison():
    c = AppController()
    c.project.add_snapshot('=опасное имя')
    c.project.front.hardpoints['ubj'].x += 3
    c.project.front.hardpoints['ubj'].z += 4
    return c


def test_dialog_filters_full_csv_and_navigation_without_mutation(qtbot, tmp_path, monkeypatch):
    c = setup_comparison()
    before = copy.deepcopy(c.project.to_dict())
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d.show()
    assert d._result is not None
    point_index = next(i for i, row in enumerate(d._result.points) if row.role == 'front' and row.code == 'ubj')
    assert d._points.item(point_index, 15).text() == '5.0'
    d._role.setCurrentIndex(2)
    d._filter.setCurrentIndex(1)
    assert d._points.isRowHidden(point_index)
    report = d._report()
    assert len(report.rows) == len(d._result.points)
    assert any('ubj' in row for row in report.rows)
    path = tmp_path / 'compare.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._export_current()
    with path.open(encoding='utf-8-sig', newline='') as f:
        exported = list(csv.reader(f, delimiter=';'))
    assert any("'=опасное имя" in row for row in exported)
    assert any('ubj' in row for row in exported)
    d._maximum.click()
    assert d._role.currentData() == 'all' and d._filter.currentData() == 'all'
    assert d._points.currentRow() == point_index and d._choose.isEnabled()
    d._choose.click()
    assert d.selection == Selection('point', 'front', 'ubj')
    assert c.project.to_dict() == before and c.undo.depth() == 0 and not c.dirty


def test_invalid_snapshot_and_removed_current_object(qtbot):
    c = setup_comparison()
    c.project.snapshots.append(Snapshot('old', data={'schema_version': 1}))
    c.project.front.hardpoints['extra'] = Hardpoint('extra', 0, 0, 0)
    c.project.add_snapshot('extra')
    c.project.front.hardpoints.pop('extra')
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d._snapshot.setCurrentIndex(1)
    assert d._result is None and not d._export.isEnabled()
    assert 'несовместим' in d._state.text()
    d._snapshot.setCurrentIndex(2)
    assert d._result is not None
    row = next(i for i, p in enumerate(d._result.points) if p.code == 'extra')
    d._points.setCurrentCell(row, 0)
    assert not d._choose.isEnabled()
    d._tabs.setCurrentIndex(1)
    assert len(d._report().rows) == len(d._result.links)
    d._links.setCurrentCell(0, 0)
    assert d._choose.isEnabled()
    link = d._result.links[0]
    d._select()
    assert d.selection == Selection('link', link.role, link.code)


def test_stale_dialog_and_protected_export(qtbot, tmp_path, monkeypatch):
    c = setup_comparison()
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    project = tmp_path / 'project.csv'
    project.write_text('untouched')
    c.project.path = str(project)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(project), ''))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d._export_current()
    assert warnings and project.read_text() == 'untouched'
    def change_while_saving(*args):
        c.modelChanged.emit()
        return str(tmp_path / 'stale.csv'), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', change_while_saving)
    d._export_current()
    assert not (tmp_path / 'stale.csv').exists()
    assert not d._choose.isEnabled() and not d._export.isEnabled() and not d._maximum.isEnabled()
    with pytest.raises(ValueError):
        d._report()


def test_main_menu_routes_selection(qtbot):
    c = setup_comparison()
    window = MainWindow(c)
    qtbot.addWidget(window)
    def select_from_dialog():
        dialog = window.findChild(SnapshotCompareDialog)
        idx = next(i for i, row in enumerate(dialog._result.points) if row.code == 'ubj' and row.role == 'front')
        dialog._points.setCurrentCell(idx, 0)
        dialog._select()
    QTimer.singleShot(0, select_from_dialog)
    window.action_compare_snapshot.trigger()
    assert c.selection == Selection('point', 'front', 'ubj')
    assert c.undo.depth() == 0 and not c.dirty


def test_empty_snapshots(qtbot):
    d = SnapshotCompareDialog(AppController())
    qtbot.addWidget(d)
    assert d._result is None and not d._export.isEnabled() and not d._choose.isEnabled()
    assert 'нет снимков' in d._state.text()
