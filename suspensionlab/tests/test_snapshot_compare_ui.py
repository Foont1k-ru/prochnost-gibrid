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


def test_parameter_tab_filter_export_units_and_navigation(qtbot, tmp_path, monkeypatch):
    from suspensionlab.model.units import UnitSettings

    c = setup_comparison()
    c.project.front.spring.rate_N_mm = 111.123456
    c.project.vehicle.name = '=bad'
    c.set_units(UnitSettings(length='in', rate='lb_in', angle='rad'))
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d.show()
    d._tabs.setCurrentIndex(2)
    spring_index = next(i for i, row in enumerate(d._parameters) if row.role == 'front' and row.code == 'spring.rate')
    assert d._params.item(spring_index, 5).text() == 'Н/мм'
    assert d._params.item(spring_index, 7).text() == '111.123456'
    assert not d._maximum.isEnabled()
    assert 'только скалярные' in d._detail.text().lower()
    d._role.setCurrentIndex(d._role.findData('vehicle'))
    d._filter.setCurrentIndex(d._filter.findData('changed'))
    assert d._params.isRowHidden(spring_index)
    report = d._report()
    assert len(report.rows) == len(d._parameters) == 83
    assert any('spring.rate' in row for row in report.rows)
    path = tmp_path / 'params.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    before, depth, dirty = copy.deepcopy(c.project.to_dict()), c.undo.depth(), c.dirty
    d._export_current()
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f, delimiter=';'))
    assert any("'=bad" in row for row in rows) and any('spring.rate' in row for row in rows)
    d._role.setCurrentIndex(0)
    d._filter.setCurrentIndex(0)
    steering = next(i for i, row in enumerate(d._parameters) if row.role == 'rear' and row.code == 'steering.ratio')
    d._params.setCurrentCell(steering, 0)
    assert not d._choose.isEnabled()
    d._params.setCurrentCell(spring_index, 0)
    assert d._choose.isEnabled()
    d._select()
    assert d.selection == Selection('spring', 'front')
    assert c.project.to_dict() == before and (c.undo.depth(), c.dirty) == (depth, dirty)


def test_parameter_tab_vehicle_navigation_and_snapshot_switch(qtbot):
    c = setup_comparison()
    c.project.vehicle.mass_kg += 42
    c.project.add_snapshot('second')
    c.project.vehicle.mass_kg += 3
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d._tabs.setCurrentIndex(2)
    index = next(i for i, row in enumerate(d._parameters) if row.code == 'vehicle.mass')
    assert d._parameters[index].delta == 45
    d._snapshot.setCurrentIndex(1)
    assert d._parameters[index].delta == 3
    d._params.setCurrentCell(index, 0)
    d._select()
    assert d.selection == Selection('vehicle')


def test_parameters_stale_and_protected_autosave(qtbot, tmp_path, monkeypatch):
    c = setup_comparison()
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d._tabs.setCurrentIndex(2)
    target = tmp_path / 'autosave.csv'
    target.write_text('saved', encoding='utf-8')
    monkeypatch.setattr('suspensionlab.ui.snapshot_compare_dialog.autosave_path', lambda: target)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), ''))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    d._export_current()
    assert warnings and target.read_text(encoding='utf-8') == 'saved'
    d._params.setCurrentCell(0, 0)
    assert d._choose.isEnabled()
    c.modelChanged.emit()
    assert not d._choose.isEnabled() and not d._export.isEnabled()
    with pytest.raises(ValueError):
        d._report()


def test_main_menu_parameter_navigation(qtbot):
    c = setup_comparison()
    window = MainWindow(c)
    qtbot.addWidget(window)
    def select_from_dialog():
        dialog = window.findChild(SnapshotCompareDialog)
        dialog._tabs.setCurrentIndex(2)
        index = next(i for i, row in enumerate(dialog._parameters)
                     if row.role == 'front' and row.code == 'damper.bump')
        dialog._params.setCurrentCell(index, 0)
        dialog._select()
    QTimer.singleShot(0, select_from_dialog)
    window.action_compare_snapshot.trigger()
    assert c.selection == Selection('damper', 'front')
    assert c.undo.depth() == 0 and not c.dirty


def test_snapshot_pair_reversal_values_filter_export_and_no_navigation(qtbot, tmp_path, monkeypatch):
    from suspensionlab.i18n import tr
    from suspensionlab.ui.snapshot_compare_dialog import _prepare

    c = AppController()
    c.project.add_snapshot('=одинаковое имя')
    c.project.front.hardpoints['ubj'].x += 3
    c.project.front.hardpoints['ubj'].z += 4
    c.project.front.spring.rate_N_mm += 10
    c.project.add_snapshot('=одинаковое имя')
    c.project.front.hardpoints['ubj'].x += 100
    c.project.front.spring.rate_N_mm += 100
    state = copy.deepcopy(c.project.to_dict())
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d.show()
    d._target.setCurrentIndex(2)  # второй снимок Б, текущий проект не используется
    point_index = next(i for i, p in enumerate(d._result.points) if p.role == 'front' and p.code == 'ubj')
    point = d._result.points[point_index]
    assert point.delta == (3, 0, 4) and point.distance == 5
    assert d._points.item(point_index, 9).text() == repr(point.new.xyz[0])
    assert 'сравниваются два снимка' in d._state.text().lower()
    d._points.setCurrentCell(point_index, 0)
    assert not d._choose.isEnabled()
    d._maximum.click()
    assert d._points.currentRow() == point_index and not d._choose.isEnabled()
    d._tabs.setCurrentIndex(1)
    d._links.setCurrentCell(0, 0)
    assert not d._choose.isEnabled()
    d._tabs.setCurrentIndex(2)
    param_index = next(i for i, p in enumerate(d._parameters) if p.role == 'front' and p.code == 'spring.rate')
    assert d._parameters[param_index].delta == 10
    d._params.setCurrentCell(param_index, 0)
    assert not d._choose.isEnabled()
    d._role.setCurrentIndex(d._role.findData('rear'))
    report = d._report()
    assert len(report.rows) == len(d._parameters) and any('spring.rate' in row for row in report.rows)
    meta = dict(report.metadata)
    assert meta[tr('snapshot_compare.snapshot_index')] == '1'
    assert meta[tr('snapshot_compare.target_index')] == '2'
    assert meta[tr('snapshot_compare.snapshot_hash')] == _prepare(c.project.snapshots[0])[1]
    assert meta[tr('snapshot_compare.target_hash')] == _prepare(c.project.snapshots[1])[1]
    assert meta[tr('snapshot_compare.snapshot_hash')] != meta[tr('snapshot_compare.target_hash')]
    path = tmp_path / 'pair.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    d._export_current()
    with path.open(encoding='utf-8-sig', newline='') as stream:
        csv_rows = list(csv.reader(stream, delimiter=';'))
    assert sum("'=одинаковое имя" in row for row in csv_rows) == 2
    assert any('spring.rate' in row for row in csv_rows)
    d._snapshot.setCurrentIndex(1)
    d._target.setCurrentIndex(1)
    point = next(p for p in d._result.points if p.role == 'front' and p.code == 'ubj')
    assert point.delta == (-3, 0, -4) and point.distance == 5
    assert next(p for p in d._parameters if p.role == 'front' and p.code == 'spring.rate').delta == -10
    d._target.setCurrentIndex(2)  # А и Б — один снимок
    point = next(p for p in d._result.points if p.role == 'front' and p.code == 'ubj')
    assert point.status == 'unchanged' and point.delta == (0, 0, 0)
    assert c.project.to_dict() == state and c.undo.depth() == 0 and not c.dirty


def test_pair_invalid_b_stale_and_export_reentrancy(qtbot, tmp_path, monkeypatch):
    c = setup_comparison()
    c.project.add_snapshot('second')
    c.project.snapshots.append(Snapshot('broken', data={'schema_version': 1}))
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d._target.setCurrentIndex(3)
    assert d._result is None and not d._export.isEnabled()
    assert 'снимок б' in d._state.text().lower()
    d._target.setCurrentIndex(2)
    assert d._result is not None and d._export.isEnabled()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    path = tmp_path / 'changed.csv'
    def switch_while_saving(*args):
        d._target.setCurrentIndex(1)
        d._target.setCurrentIndex(2)  # Даже возврат к тому же выбору отменяет экспорт.
        return str(path), ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', switch_while_saving)
    d._export_current()
    assert warnings and not path.exists()
    c.modelChanged.emit()
    assert not d._target.isEnabled() and not d._snapshot.isEnabled() and not d._export.isEnabled()
    with pytest.raises(ValueError):
        d._report()


def test_pair_different_axle_types_are_not_comparable(qtbot):
    c = AppController()
    c.project.add_snapshot('independent')
    c.project.set_axle_type('rear', 'live_axle_coil')
    c.project.add_snapshot('solid')
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d._target.setCurrentIndex(2)
    point = next(p for p in d._result.points if p.role == 'rear' and p.old and p.new)
    assert point.status == 'incompatible' and point.delta is None
    param = next(p for p in d._parameters if p.role == 'rear' and p.code == 'spring.rate')
    assert param.status == 'incompatible' and param.delta is None
    assert 'multilink_rear' in d._context.text() and 'live_axle_coil' in d._context.text()


def test_pair_uses_saved_rounded_values_not_live_model(qtbot):
    c = AppController()
    c.project.front.hardpoints['ubj'].x = 0.123456
    c.project.add_snapshot('A')
    c.project.front.hardpoints['ubj'].x = 0.123454
    c.project.add_snapshot('B')
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    current = next(p for p in d._result.points if p.role == 'front' and p.code == 'ubj')
    assert current.status == 'changed' and current.new.xyz[0] == 0.123454
    d._target.setCurrentIndex(2)
    pair = next(p for p in d._result.points if p.role == 'front' and p.code == 'ubj')
    assert pair.status == 'unchanged' and pair.old.xyz[0] == pair.new.xyz[0] == 0.1235


def test_pair_added_removed_follow_direction(qtbot):
    c = AppController()
    c.project.front.hardpoints['only_a'] = Hardpoint('only_a', 1, 2, 3)
    c.project.add_snapshot('A')
    del c.project.front.hardpoints['only_a']
    c.project.front.hardpoints['only_b'] = Hardpoint('only_b', 4, 5, 6)
    c.project.add_snapshot('B')
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d._target.setCurrentIndex(2)
    points = {p.code: p for p in d._result.points if p.role == 'front'}
    assert points['only_a'].status == 'removed' and points['only_b'].status == 'added'
    d._snapshot.setCurrentIndex(1)
    d._target.setCurrentIndex(1)
    points = {p.code: p for p in d._result.points if p.role == 'front'}
    assert points['only_a'].status == 'added' and points['only_b'].status == 'removed'
