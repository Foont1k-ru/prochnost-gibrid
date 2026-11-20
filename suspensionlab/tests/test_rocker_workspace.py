"""Связь отдельно заданного коромысла с реальными решателями подвески."""
from math import dist, isfinite

import numpy as np
import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.rear_five_link import RearFiveLink
from suspensionlab.core.rocker_kinematics import RockerGeometry
from suspensionlab.core.rocker_workspace import calculate_rocker
from suspensionlab.core.springs import lower_arm_point
from suspensionlab.core.sweep import limited_sweep
from suspensionlab.model.templates import load_template


def example_geometry(axle, code):
    # Test fixture only: arbitrary pivots do not represent a safe design.
    bx, by, bz = axle.hardpoints[code].as_tuple()
    x, y, z = bx + 30., by - 20., bz + 10.
    return RockerGeometry((x + 100, y + 20, z + 100), (1, 0, 0),
                          (x + 100, y + 70, z + 100), (x, y, z),
                          (x + 100, y + 20, z + 130), (x + 100, y + 100, z + 160))


@pytest.mark.parametrize(('role', 'point', 'mount'), [
    ('front', 'lbj', 'lower_arm'), ('front', 'lbj', 'upright'), ('rear', 'uf_out', 'upright'),
])
def test_rocker_follows_each_actual_suspension_pose_without_mutating_project(role, point, mount):
    project = load_template('ring')
    before = project.to_dict()
    axle = project.axle(role)
    geometry = example_geometry(axle, point)
    samples = calculate_rocker(axle, geometry, mount, -6, 6)
    assert project.to_dict() == before
    assert [s.travel_mm for s in samples] == [-6, -4, -2, 0, 2, 4, 6]
    assert all(s.pose is not None and s.error is None for s in samples)
    model = DoubleWishbone(axle, 'left') if role == 'front' else RearFiveLink(axle, 'left')
    solver = limited_sweep(model, [s.travel_mm for s in samples], max_step_mm=2)
    for sample, row in zip(samples, solver.points, strict=True):
        original = np.array(geometry.rod_suspension)
        moving = (lower_arm_point(model, row.pose, original) if mount == 'lower_arm' else
                  row.pose.point(original, model.center0))
        assert dist(sample.pose.rod_rocker, moving) == pytest.approx(geometry.rod_length, abs=1e-7)
        assert sample.pose.damper_length_mm == pytest.approx(dist(sample.pose.damper_rocker, geometry.damper_body))
    zero = samples[3]
    assert zero.pose.rod_rocker == pytest.approx(geometry.rod_rocker)
    assert zero.pose.damper_rocker == pytest.approx(geometry.damper_rocker)
    assert samples[0].motion_ratio is None and samples[-1].motion_ratio is None
    assert all(s.motion_ratio is not None and isfinite(s.motion_ratio) for s in samples[1:-1])
    assert samples[1].motion_ratio != pytest.approx(samples[-2].motion_ratio, abs=1e-4)


def test_rod_attachment_is_not_silently_treated_as_upright_or_body():
    axle = load_template('ring').front
    geometry = example_geometry(axle, 'lbj')
    arm = calculate_rocker(axle, geometry, 'lower_arm', -6, 6)
    upright = calculate_rocker(axle, geometry, 'upright', -6, 6)
    assert arm[-1].pose is not None and upright[-1].pose is not None
    assert abs(arm[-1].pose.damper_length_mm - upright[-1].pose.damper_length_mm) > 1e-3
    with pytest.raises(ValueError):
        calculate_rocker(axle, geometry, 'body', -6, 6)
    with pytest.raises(ValueError):
        calculate_rocker(load_template('ring').rear, geometry, 'lower_arm', -6, 6)


def test_incorrect_range_and_unsupported_scheme_are_rejected():
    project = load_template('ring')
    geometry = example_geometry(project.front, 'lbj')
    for start, end in ((1, 10), (-10, -1), (-151, 0), (0, 151), (float('nan'), 0), (True, 0)):
        with pytest.raises(ValueError):
            calculate_rocker(project.front, geometry, 'upright', start, end)
    unsupported = load_template('live_axle').rear
    with pytest.raises(ValueError):
        calculate_rocker(unsupported, geometry, 'upright', -6, 6)


def test_failed_suspension_branch_never_reuses_rocker_pose(monkeypatch):
    from suspensionlab.core.double_wishbone import KinematicsError

    axle = load_template('ring').front
    geometry = example_geometry(axle, 'lbj')
    initial_step = DoubleWishbone._step
    def fail_on_bump(self, pose, travel):
        if travel > 2.01:
            raise KinematicsError(travel, 'deliberate failure')
        return initial_step(self, pose, travel)
    monkeypatch.setattr(DoubleWishbone, '_step', fail_on_bump)
    samples = {s.travel_mm: s for s in calculate_rocker(axle, geometry, 'upright', -6, 6)}
    assert samples[-6].pose is not None and samples[2].pose is not None
    assert samples[4].pose is None and samples[4].error == 'no suspension pose'
    assert samples[6].pose is None and samples[6].error == 'not evaluated after branch failure'
    assert samples[2].motion_ratio is None


def test_undetermined_static_rocker_does_not_return_a_false_length():
    axle = load_template('ring').front
    x, y, z = axle.hardpoints['lbj'].as_tuple()
    # The rod attachment is exactly on the line causing a tangent zero pose.
    geometry = RockerGeometry((x + 100, y, z + 100), (1, 0, 0),
                              (x + 100, y, z + 150), (x, y, z),
                              (x + 100, y + 30, z + 100), (x + 100, y + 30, z + 180))
    result = calculate_rocker(axle, geometry, 'upright', -6, 6)
    assert all(sample.pose is None and sample.motion_ratio is None and sample.error for sample in result)


def test_requested_samples_are_in_dense_continuation_grid():
    axle = load_template('ring').front
    geometry = example_geometry(axle, 'lbj')
    targets = [-27., -18., -9., 0., 7.666666666666667, 15.333333333333334, 23.]
    samples = calculate_rocker(axle, geometry, 'upright', -27, 23, targets=targets)
    times = [s.travel_mm for s in samples]
    assert all(target in times for target in targets)
    assert all(0 < b - a <= 2.000000001 for a, b in zip(times, times[1:], strict=False))
    for invalid in ([float('nan')], [24.], [True]):
        with pytest.raises(ValueError):
            calculate_rocker(axle, geometry, 'upright', -27, 23, targets=invalid)
