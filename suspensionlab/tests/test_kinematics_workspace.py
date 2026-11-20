"""Рабочая область не подменяет сходимость физической пригодностью."""
from copy import deepcopy

import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError
from suspensionlab.core.kinematics_workspace import calculate, moved_link_end, static_scene
from suspensionlab.model.templates import load_template


def test_discrete_calculation_uses_solver_without_changing_project():
    project = load_template('ring')
    before = deepcopy(project.to_dict())
    result = calculate(project.front, -30, 30, 10)
    assert [s.travel_mm for s in result.samples] == [-30, -20, -10, 0, 10, 20, 30]
    assert all(s.scene is not None and s.error is None for s in result.samples)
    expected = DoubleWishbone(project.front).solve(20)
    actual = result.samples[5].scene.point('wheel_center')
    assert actual == pytest.approx(expected.center)
    assert project.to_dict() == before


def test_failed_poses_are_not_filled_with_old_results(monkeypatch):
    initial = DoubleWishbone._step
    def fail(self, pose, travel):
        if travel > 11:
            raise KinematicsError(travel, 'тестовый отказ')
        return initial(self, pose, travel)
    monkeypatch.setattr(DoubleWishbone, '_step', fail)
    result = calculate(load_template('ring').front, -20, 30, 10)
    by_travel = {s.travel_mm: s for s in result.samples}
    assert by_travel[10].scene is not None
    assert by_travel[20].scene is None and 'тестовый отказ' in by_travel[20].error
    assert by_travel[30].scene is None and 'тестовый отказ' in by_travel[30].error
    assert result.reached_bump_mm <= 11


def test_unsupported_is_only_static_and_invalid_grid_rejected():
    project = load_template('ring')
    frame, links = static_scene(project.rear)
    assert frame.segments and links
    with pytest.raises(ValueError, match='не реализован'):
        calculate(project.rear, -30, 30, 10)
    for args in [(-200, 30, 10), (-30, 30, 1), (20, 30, 10)]:
        with pytest.raises(ValueError):
            calculate(project.front, *args)


def test_link_length_is_distance_to_axis_and_does_not_mutate_input():
    axle = load_template('ring').front
    before = deepcopy(axle.hardpoints['lbj'].as_tuple())
    code, xyz = moved_link_end(axle, 'lower_arm', 500)
    assert code == 'lbj' and axle.hardpoints[code].as_tuple() == before
    axle.hardpoints[code].x, axle.hardpoints[code].y, axle.hardpoints[code].z = xyz
    assert axle.link_length('lower_arm') == pytest.approx(500)
    axle.hardpoints['lca_r_in'].x, axle.hardpoints['lca_r_in'].y, axle.hardpoints['lca_r_in'].z = axle.hardpoints['lca_f_in'].as_tuple()
    with pytest.raises(ValueError, match='совпадают'):
        moved_link_end(axle, 'lower_arm', 500)
