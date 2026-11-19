"""Снимок использует только решённые дискретные позы и не двигает опоры."""
from copy import deepcopy

import pytest

from suspensionlab.model.fixed_arm_skeleton import SkeletonError, capture_fixed_arm, preview_fixed_arm
from suspensionlab.model.templates import load_template


def test_frozen_anchors_and_spatial_bend_do_not_change_project():
    project = load_template('ring')
    before = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20, spacing_mm=10)
    straight = preview_fixed_arm(snapshot, project, 10, 2)
    start, end = straight.anchors[0], straight.anchors[2]
    # A non-collinear point in 3D, far enough from both endpoints for a small bend.
    vertex = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2,
              (start[2] + end[2]) / 2 + 50]
    bent = preview_fixed_arm(snapshot, project, 10, 2, {'front': {'vertex_mm': vertex, 'radius_mm': 20}})
    assert bent.anchors == straight.anchors
    frozen = snapshot.project_copy()
    for code, actual in zip(('lca_f_in', 'lca_r_in', 'lbj'), straight.anchors, strict=True):
        assert actual == frozen.front.hardpoints[code].as_tuple()
    assert bent.centerlines[0][0] == straight.anchors[0]
    assert bent.centerlines[0][-1] == straight.anchors[2]
    assert bent.centerlines[1][0] == straight.anchors[1]
    assert bent.centerlines[1][-1] == straight.anchors[2]
    assert bent.centerlines != straight.centerlines and project.to_dict() == before
    assert snapshot.travels_mm == (-20, -10, 0, 10, 20)
    assert snapshot.max_residual_mm < 1e-8


def test_conflict_and_stale_project_never_rebase_snapshot():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -10, 10)
    before = preview_fixed_arm(snapshot, project, 10, 2)
    with pytest.raises(SkeletonError, match='вершина изгиба совпадает с опорой'):
        preview_fixed_arm(snapshot, project, 10, 2,
                          {'front': {'vertex_mm': list(before.anchors[0]), 'radius_mm': 20}})
    assert preview_fixed_arm(snapshot, project, 10, 2) == before
    point = project.front.hardpoints['lbj']
    point.x += 0.000001  # below the serialization rounding precision
    assert not snapshot.matches(project)
    with pytest.raises(SkeletonError, match='изменился'):
        preview_fixed_arm(snapshot, project, 10, 2)
    point.x -= 0.000001
    assert snapshot.matches(project)
    assert preview_fixed_arm(snapshot, project, 10, 2) == before
    point.x += 10
    new = capture_fixed_arm(project, -10, 10)
    assert preview_fixed_arm(new, project, 10, 2).anchors != before.anchors
    assert not snapshot.matches(project)


def test_complete_project_change_is_conservatively_stale():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, 0, 0)
    project.meta.name = 'другой проект'
    assert not snapshot.matches(project)
    with pytest.raises(SkeletonError, match='изменился'):
        preview_fixed_arm(snapshot, project, 10, 2)


def test_snapshot_rejects_invalid_geometry_and_grid():
    project = load_template('ring')
    with pytest.raises(SkeletonError):
        capture_fixed_arm(project, -20, 20, spacing_mm=0)
    with pytest.raises(SkeletonError):
        capture_fixed_arm(project, 1, 20)
    point = project.front.hardpoints['lca_f_in']
    other = project.front.hardpoints['lca_r_in']
    point.x, point.y, point.z = other.x, other.y, other.z
    with pytest.raises(SkeletonError, match='рассчитать'):
        capture_fixed_arm(project, -10, 10)


def test_snapshot_rejects_unsolved_requested_position():
    project = load_template('ring')
    # A 100 mm parallelogram cannot reach a 150 mm vertical displacement.
    points = {
        'uca_f_in': (100, 300, 400), 'uca_r_in': (-100, 300, 400), 'ubj': (0, 400, 400),
        'lca_f_in': (100, 300, 150), 'lca_r_in': (-100, 300, 150), 'lbj': (0, 400, 150),
        'tierod_in': (-150, 300, 200), 'tierod_out': (-150, 400, 200), 'wheel_center': (0, 450, 310),
    }
    for code, coords in points.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = coords
    with pytest.raises(SkeletonError, match='Нет решения'):
        capture_fixed_arm(project, -150, 150, spacing_mm=10)


def test_project_copy_is_independent():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, 0, 0)
    copy = snapshot.project_copy()
    copy.front.hardpoints['lbj'].x += 100
    assert snapshot.matches(project)
    assert snapshot.project_copy().front.hardpoints['lbj'].x != copy.front.hardpoints['lbj'].x
