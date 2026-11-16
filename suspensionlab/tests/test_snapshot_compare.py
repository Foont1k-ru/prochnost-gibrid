import copy
import math

import pytest

from suspensionlab.core.snapshot_compare import compare_projects, max_link_delta, max_point_displacement
from suspensionlab.model.entities import Hardpoint, Project
from suspensionlab.model.snapshot_restore import prepare_snapshot


def test_points_and_links_are_compared_without_changing_projects():
    current = Project.create_default()
    current.add_snapshot('reference')
    reference = prepare_snapshot(current.snapshots[0].data)
    current.front.hardpoints['ubj'].x += 3
    current.front.hardpoints['ubj'].z += 4
    before = copy.deepcopy(current.to_dict())
    result = compare_projects(reference, current)
    point = next(r for r in result.points if r.role == 'front' and r.code == 'ubj')
    assert point.status == 'changed' and point.delta == (3, 0, 4) and point.distance == 5
    assert max_point_displacement(result.points) == result.points.index(point)
    assert any(r.role == 'front' and r.status == 'changed' and r.delta is not None for r in result.links)
    for link in result.links:
        if link.role == 'front' and link.old_exists and link.new_exists and link.status != 'invalid':
            assert link.new_length == pytest.approx(current.front.link_length(link.code))
            assert link.old_length == pytest.approx(reference.front.link_length(link.code))
    assert current.to_dict() == before


def test_saved_rounding_is_visible_and_comparison_is_exact():
    current = Project.create_default()
    current.front.hardpoints['ubj'].x = 0.123456789
    current.add_snapshot('rounding')
    result = compare_projects(prepare_snapshot(current.snapshots[0].data), current)
    point = next(r for r in result.points if r.role == 'front' and r.code == 'ubj')
    assert point.old.xyz[0] == 0.1235
    assert point.new.xyz[0] == 0.123456789
    assert point.status == 'changed' and point.distance > 0


def test_added_removed_types_and_nonfinite_are_not_zero():
    original = Project.create_default()
    current = Project.create_default()
    original.front.hardpoints['old_extra'] = Hardpoint('old_extra', 1, 2, 3)
    current.front.hardpoints['new_extra'] = Hardpoint('new_extra', 1, 2, 3)
    current.front.hardpoints['ubj'].x = math.nan
    current.set_axle_type('rear', 'live_axle_coil')
    result = compare_projects(original, current)
    def row(role, code):
        return next(r for r in result.points if r.role == role and r.code == code)
    assert row('front', 'old_extra').status == 'removed' and row('front', 'old_extra').distance is None
    assert row('front', 'new_extra').status == 'added' and row('front', 'new_extra').delta is None
    assert row('front', 'ubj').status == 'invalid' and row('front', 'ubj').distance is None
    common = next(r for r in result.points if r.role == 'rear' and r.old and r.new)
    assert common.old_type != common.new_type and common.status == 'incompatible' and common.delta is None
    invalid_link = next(r for r in result.links if r.role == 'front' and r.code == 'upper_arm')
    assert invalid_link.status == 'invalid' and invalid_link.new_length is None and invalid_link.delta is None


def test_degenerate_axis_missing_points_and_maxima_ties():
    current = Project.create_default()
    reference = Project.create_default()
    current.front.hardpoints['uca_r_in'].x = current.front.hardpoints['uca_f_in'].x
    current.front.hardpoints['uca_r_in'].y = current.front.hardpoints['uca_f_in'].y
    current.front.hardpoints['uca_r_in'].z = current.front.hardpoints['uca_f_in'].z
    current.rear.hardpoints.pop('spring_lo')
    result = compare_projects(reference, current)
    upper = next(r for r in result.links if r.role == 'front' and r.code == 'upper_arm')
    assert upper.status == 'invalid' and upper.new_length is None
    assert max_link_delta(result.links) is not None
    same = compare_projects(reference, reference)
    assert max_point_displacement(same.points) == 0
    assert max_link_delta(same.links) == 0
    assert max_point_displacement(()) is None and max_link_delta(()) is None


def test_representation_mismatch_and_overflow_are_unavailable(monkeypatch):
    from dataclasses import replace

    from suspensionlab.core import snapshot_compare
    from suspensionlab.model.point_csv import capture_points

    original = Project.create_default()
    current = Project.create_default()
    original.front.hardpoints['ubj'].x = -1e308
    current.front.hardpoints['ubj'].x = 1e308
    def custom_capture(project):
        points = capture_points(project)
        if project is current:
            return tuple(replace(p, representation='single') if p.code == 'spring_lo' and p.role == 'front' else p
                         for p in points)
        return points
    monkeypatch.setattr(snapshot_compare, 'capture_points', custom_capture)
    result = compare_projects(original, current)
    overflow = next(r for r in result.points if r.role == 'front' and r.code == 'ubj')
    assert overflow.status == 'invalid' and overflow.delta is None
    mismatch = next(r for r in result.points if r.role == 'front' and r.code == 'spring_lo')
    assert mismatch.status == 'incompatible' and mismatch.distance is None
