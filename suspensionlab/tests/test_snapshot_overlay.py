from dataclasses import replace

import pytest

from suspensionlab.core.snapshot_compare import compare_projects
from suspensionlab.core.snapshot_overlay import MAX_COORD_MM, make_overlay, project_point
from suspensionlab.model.entities import Project


def rows():
    original, new = Project.create_default(), Project.create_default()
    new.front.hardpoints['ubj'].x += 3
    new.front.hardpoints['ubj'].z += 4
    return compare_projects(original, new).points


def test_projections_match_primary_canvas():
    assert project_point((1, 2, 3), 'front') == (-2, 3)
    assert project_point((1, 2, 3), 'side') == (-1, 3)
    assert project_point((1, 2, 3), 'top') == (-1, 2)
    with pytest.raises(ValueError):
        project_point((1, 2, 3), 'bad')


def test_role_projection_and_status_control_connections_without_inventing_mirrors():
    all_rows = rows()
    ubj_i = next(i for i, row in enumerate(all_rows) if row.role == 'front' and row.code == 'ubj')
    data = make_overlay(all_rows, 'front', 'front')
    points = [p for p in data.points if p.row == ubj_i]
    assert len(points) == 2 and {p.source for p in points} == {'A', 'B'}
    old, new = all_rows[ubj_i].old, all_rows[ubj_i].new
    assert (points[0].u, points[0].v) == (-old.xyz[1], old.xyz[2])
    assert (points[1].u, points[1].v) == (-new.xyz[1], new.xyz[2])
    assert ubj_i in data.connected_rows
    assert all(all_rows[p.row].role == 'front' for p in data.points)
    assert not data.omitted_rows
    incompatible = replace(all_rows[ubj_i], status='incompatible', delta=None, distance=None)
    removed = replace(all_rows[ubj_i], new=None, status='removed', delta=None, distance=None)
    added = replace(all_rows[ubj_i], old=None, status='added', delta=None, distance=None)
    custom = make_overlay((incompatible, removed, added), 'front', 'side')
    assert len(custom.points) == 4 and not custom.connected_rows
    assert [(p.row, p.source) for p in custom.points] == [(0, 'A'), (0, 'B'), (1, 'A'), (2, 'B')]
    with pytest.raises(ValueError):
        make_overlay(all_rows, 'bad', 'front')


def test_invalid_and_extreme_rows_omitted_entirely_and_counted():
    base = next(r for r in rows() if r.role == 'front' and r.code == 'ubj')
    invalid = replace(base, status='invalid')
    extreme = replace(base, new=replace(base.new, xyz=(MAX_COORD_MM + 1, 2, 3)))
    finite_edge = replace(base, new=replace(base.new, xyz=(MAX_COORD_MM, 2, 3)))
    nan = replace(base, old=replace(base.old, xyz=(float('nan'), 1, 2)))
    data = make_overlay((invalid, extreme, finite_edge, nan), 'front', 'top')
    assert data.omitted_rows == (0, 1, 3)
    assert {p.row for p in data.points} == {2}
    assert data.connected_rows == (2,)
    assert make_overlay((invalid,), 'rear', 'top').points == ()
