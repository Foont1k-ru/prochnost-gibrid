import copy
import math

from PySide6.QtCore import Qt, QTimer

from suspensionlab.core.snapshot_compare import compare_projects
from suspensionlab.model.entities import Project
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.snapshot_compare_dialog import SnapshotCompareDialog
from suspensionlab.ui.snapshot_overlay_dialog import SnapshotOverlayDialog


def controller():
    c = AppController()
    c.project.add_snapshot('A')
    c.project.front.hardpoints['ubj'].x += 32
    c.project.front.hardpoints['ubj'].z += 46
    c.project.add_snapshot('B')
    return c


def test_interactive_overlay_projection_selection_filter_and_scale(qtbot):
    c = controller()
    ref = Project.from_dict(c.project.snapshots[0].data)
    rows = compare_projects(ref, c.project).points
    dialog = SnapshotOverlayDialog(c, rows)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    index = next(i for i, row in enumerate(rows) if row.role == 'front' and row.code == 'ubj')
    point = next(p for p in dialog._canvas.screen_points() if p[0] == index and p[1] == 'B')[2]
    qtbot.mouseClick(dialog._canvas, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert dialog._current_row() == index
    assert 'ubj' in dialog._detail.text() and '3D-перемещение' in dialog._detail.text()
    assert dialog._choose.isEnabled()
    coords_before = [(r, s, p.x(), p.y()) for r, s, p in dialog._canvas.screen_points() if r == index]
    dialog._filter.setCurrentIndex(dialog._filter.findData('changed'))
    coords_after = [(r, s, p.x(), p.y()) for r, s, p in dialog._canvas.screen_points() if r == index]
    assert coords_before == coords_after
    assert dialog._current_row() == index and dialog._list.count() >= 1
    dialog._projection.setCurrentIndex(dialog._projection.findData('side'))
    assert 'X влево' in dialog._counts.text()
    points = [p for p in dialog._canvas.screen_points() if p[0] == index]
    assert len(points) == 2 and not math.isclose(points[0][2].x(), points[1][2].x())
    dialog._role.setCurrentIndex(dialog._role.findData('rear'))
    assert dialog._current_row() == -1 and not dialog._choose.isEnabled()
    dialog._filter.setCurrentIndex(0)
    assert dialog._list.count() > 0
    dialog._list.setCurrentRow(0)
    expected = dialog._current_row()
    dialog._return_row()
    assert dialog.selected_row == expected
    assert c.undo.depth() == 0 and not c.dirty


def test_dialog_returns_to_full_table_for_snapshot_pair(qtbot):
    c = controller()
    before = copy.deepcopy(c.project.to_dict())
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d._target.setCurrentIndex(2)
    d._role.setCurrentIndex(d._role.findData('rear'))
    d._filter.setCurrentIndex(d._filter.findData('unchanged'))
    def choose_front_point():
        child = d.findChild(SnapshotOverlayDialog)
        child._role.setCurrentIndex(child._role.findData('front'))
        index = next(i for i, row in enumerate(child.rows) if row.role == 'front' and row.code == 'ubj')
        child._pick_row(index)
        child._return_row()
    QTimer.singleShot(0, choose_front_point)
    d._open_overlay()
    assert d._tabs.currentIndex() == 0
    point = d._result.points[d._points.currentRow()]
    assert point.code == 'ubj' and point.role == 'front'
    assert d._role.currentData() == d._filter.currentData() == 'all'
    assert not d._choose.isEnabled()  # Б — снимок, не текущий проект
    assert c.project.to_dict() == before and c.undo.depth() == 0 and not c.dirty


def test_stale_parent_and_child_prevent_navigation(qtbot):
    c = controller()
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    def invalidate_child():
        child = d.findChild(SnapshotOverlayDialog)
        child._list.setCurrentRow(0)
        assert child._choose.isEnabled()
        c.modelChanged.emit()
        assert not child._choose.isEnabled() and not child._canvas.isEnabled()
        assert not d._overlay.isEnabled()
        child._return_row()
        assert child.selected_row is None
        child.reject()
    QTimer.singleShot(0, invalidate_child)
    d._open_overlay()
    assert d._stale and not d._export.isEnabled()


def test_omitted_rows_remain_accessible_in_list(qtbot):
    from dataclasses import replace

    from suspensionlab.core.snapshot_overlay import MAX_COORD_MM

    c = controller()
    rows = list(compare_projects(Project.from_dict(c.project.snapshots[0].data), c.project).points)
    index = next(i for i, row in enumerate(rows) if row.role == 'front' and row.code == 'ubj')
    rows[index] = replace(rows[index], new=replace(rows[index].new, xyz=(MAX_COORD_MM + 1, 0, 0)))
    dialog = SnapshotOverlayDialog(c, tuple(rows))
    qtbot.addWidget(dialog)
    assert index in dialog._data.omitted_rows
    assert all(p.row != index for p in dialog._data.points)
    assert 'схеме (некорректные или за ±1 млрд мм): 1' in dialog._counts.text()
    dialog._pick_row(index)
    assert dialog._current_row() == index and dialog._choose.isEnabled()
    dialog._return_row()
    assert dialog.selected_row == index


def test_changing_source_invalidates_open_overlay(qtbot):
    c = controller()
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    def switch_source():
        child = d.findChild(SnapshotOverlayDialog)
        child._list.setCurrentRow(0)
        d._target.setCurrentIndex(2)
        assert child._stale and not child._choose.isEnabled()
        child._return_row()
        assert child.selected_row is None
        child.reject()
    QTimer.singleShot(0, switch_source)
    d._open_overlay()
    assert d._result is not None and not d._stale
    assert d._target.currentData() == 1


def test_zoom_centers_b_and_fit_restores_extent(qtbot):
    c = controller()
    ref = Project.from_dict(c.project.snapshots[0].data)
    rows = compare_projects(ref, c.project).points
    d = SnapshotOverlayDialog(c, rows)
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    index = next(i for i, row in enumerate(rows) if row.role == 'front' and row.code == 'ubj')
    d._pick_row(index)
    before = next(point for row, source, point in d._canvas.screen_points() if row == index and source == 'B')
    d._zoom.setCurrentIndex(d._zoom.findData(4.0))
    after = next(point for row, source, point in d._canvas.screen_points() if row == index and source == 'B')
    assert math.isclose(after.x(), d._canvas.width() / 2, abs_tol=1e-6)
    assert math.isclose(after.y(), d._canvas.height() / 2, abs_tol=1e-6)
    assert before != after
    d._zoom.setCurrentIndex(0)
    restored = next(point for row, source, point in d._canvas.screen_points() if row == index and source == 'B')
    assert restored == before


def test_overlay_keeps_sources_and_types_in_context(qtbot):
    from PySide6.QtWidgets import QLineEdit

    c = controller()
    d = SnapshotCompareDialog(c)
    qtbot.addWidget(d)
    d._target.setCurrentIndex(2)
    def inspect_context():
        child = d.findChild(SnapshotOverlayDialog)
        fields = child.findChildren(QLineEdit)
        assert [f.text() for f in fields] == ['1. A', '2. B']
        assert all(f.isReadOnly() for f in fields)
        assert child._canvas.data.points
        child.reject()
    QTimer.singleShot(0, inspect_context)
    d._open_overlay()
