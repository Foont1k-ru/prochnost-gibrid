"""Независимые геометрические проверки пятирычажной кинематики."""
from copy import deepcopy

import numpy as np
import pytest
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from suspensionlab.core.double_wishbone import KinematicsError
from suspensionlab.core.kinematics_workspace import calculate, rear_scene
from suspensionlab.core.metrics import wheel_angles
from suspensionlab.core.rear_five_link import LINKS, RearFiveLink
from suspensionlab.core.sweep import limited_sweep
from suspensionlab.model.templates import load_template


def synthetic_known_pose():
    """Строим опоры на серединных плоскостях двух известных положений."""
    axle = deepcopy(load_template('ring').rear)
    center = np.array([0., 762., 310.])
    displacement = np.array([1.0, -0.8, 6.0])
    rotation = Rotation.from_rotvec([0.008, -0.012, 0.009]).as_matrix()
    outers = [np.array(p) for p in ([120., 680., 420.], [-140., 690., 430.],
                                   [130., 700., 160.], [-160., 700., 150.], [-240., 690., 300.])]
    candidates = [np.array(p) for p in ([0., -350., 100.], [100., -400., -100.],
                                       [-150., -350., 150.], [150., -300., -80.], [-200., -350., 200.])]
    axle.hardpoints['wheel_center'].x, axle.hardpoints['wheel_center'].y, axle.hardpoints['wheel_center'].z = center
    for (_, inner, outer), start, candidate in zip(LINKS, outers, candidates, strict=True):
        moved = center + displacement + rotation @ (start - center)
        delta = moved - start
        offset = candidate - delta * (np.dot(candidate, delta) / np.dot(delta, delta))
        anchor = (start + moved) / 2 + offset
        for code, xyz in ((inner, anchor), (outer, start)):
            point = axle.hardpoints[code]
            point.x, point.y, point.z = map(float, xyz)
    return axle, center + displacement, rotation


def test_synthetic_pose_known_independently():
    axle, target_center, target_rotation = synthetic_known_pose()
    model = RearFiveLink(axle)
    pose = model.solve(6.0, max_step_mm=0.5)
    assert pose.center == pytest.approx(target_center, abs=1e-6)
    assert pose.rotation == pytest.approx(target_rotation, abs=1e-8)
    for _, inner, outer in LINKS:
        fixed = model.points[inner]
        original = model.points[outer]
        actual = pose.point(original, model.center0)
        assert np.linalg.norm(actual - fixed) == pytest.approx(np.linalg.norm(original - fixed), abs=1e-7)


def test_default_rear_solutions_match_independent_scipy_equations():
    axle = load_template('ring').rear
    before = deepcopy(axle.hardpoints)
    model = RearFiveLink(axle)
    for travel in (-30., -15., 0., 15., 30.):
        pose = model.solve(travel)
        # Independently express six unknowns as translation and a rotation vector;
        # residuals are unnormalised squared-length differences, not solver internals.
        def residual(x, travel=travel):
            center = model.center0 + x[:3]
            rotation = Rotation.from_rotvec(x[3:]).as_matrix()
            terms = []
            for _, inner, outer in LINKS:
                local = model.points[outer] - model.center0
                v = center + rotation @ local - model.points[inner]
                ref = model.points[outer] - model.points[inner]
                terms.append((np.dot(v, v) - np.dot(ref, ref)) / 1000.)
            return [*terms, center[2] - model.center0[2] - travel]
        expected = [*(pose.center - model.center0), *Rotation.from_matrix(pose.rotation).as_rotvec()]
        reference = least_squares(residual, [0., 0., travel, 0., 0., 0.], xtol=1e-13, ftol=1e-13, gtol=1e-13)
        assert reference.success and np.max(np.abs(residual(reference.x))) < 1e-7
        assert reference.x == pytest.approx(expected, abs=1e-7)
        assert np.linalg.det(pose.rotation) == pytest.approx(1, abs=1e-10)
        assert pose.rotation.T @ pose.rotation == pytest.approx(np.eye(3), abs=1e-10)
        assert pose.center[2] == pytest.approx(model.center0[2] + travel, abs=1e-9)
    assert axle.hardpoints == before


def test_jacobian_matches_finite_differences_at_moving_pose():
    model = RearFiveLink(load_template('ring').rear)
    pose = model.solve(15)
    residual, jac = model._system(pose.center, pose.rotation, 15)
    h = 1e-5
    numeric = np.empty((6, 6))
    for i in range(6):
        plus, minus = np.zeros(6), np.zeros(6)
        plus[i], minus[i] = h, -h
        rp = Rotation.from_rotvec(plus[3:]).as_matrix() @ pose.rotation
        rm = Rotation.from_rotvec(minus[3:]).as_matrix() @ pose.rotation
        numeric[:, i] = (model._residual(pose.center + plus[:3], rp, 15) -
                         model._residual(pose.center + minus[:3], rm, 15)) / (2 * h)
    assert max(abs(residual)) < 1e-8
    assert jac == pytest.approx(numeric, abs=2e-6)


def test_mirrored_side_and_scene_keep_link_lengths_and_wheel_angles():
    axle = load_template('ring').rear
    left, right = RearFiveLink(axle, 'left'), RearFiveLink(axle, 'right')
    lp, rp = left.solve(25), right.solve(25)
    mirror = np.diag([1., -1., 1.])
    assert rp.center == pytest.approx(mirror @ lp.center, abs=1e-7)
    assert rp.rotation == pytest.approx(mirror @ lp.rotation @ mirror, abs=1e-8)
    assert wheel_angles(left, lp, static_camber_deg=-1, static_toe_deg=.1) == pytest.approx(
        wheel_angles(right, rp, static_camber_deg=-1, static_toe_deg=.1), abs=1e-8)
    scene = rear_scene(left, lp, axle)
    for _, inner, outer in LINKS:
        assert scene.point(inner) == pytest.approx(left.points[inner])
        assert scene.point(outer) == pytest.approx(lp.point(left.points[outer], left.center0))
    assert len([s for s in scene.segments if s.kind == 'wheel']) == 72


def test_translation_of_all_anchors_preserves_relative_motion():
    axle = load_template('ring').rear
    shifted = deepcopy(axle)
    offset = np.array([193.2, -80.1, 77.])
    for point in shifted.hardpoints.values():
        point.x += offset[0]
        point.y += offset[1]
        point.z += offset[2]
    original = RearFiveLink(axle).solve(-30)
    moved = RearFiveLink(shifted).solve(-30)
    assert moved.center == pytest.approx(original.center + offset, abs=1e-7)
    assert moved.rotation == pytest.approx(original.rotation, abs=1e-9)


def test_actual_large_excursion_stops_instead_of_fabricating_poses():
    model = RearFiveLink(load_template('ring').rear)
    sweep = limited_sweep(model, [-500, -300, 0, 300, 500])
    assert sweep.points[0].pose is None and sweep.points[0].error is not None
    assert sweep.points[1].pose is None and sweep.points[1].error is not None
    assert sweep.points[2].pose is not None and sweep.points[3].pose is not None
    assert sweep.points[4].pose is None and sweep.points[4].error is not None
    assert -300 < sweep.reachable_droop_mm < 0 < sweep.reachable_bump_mm < 500


def test_invalid_type_missing_point_coincident_and_singular_are_rejected():
    project = load_template('ring')
    with pytest.raises(ValueError, match='пятирычажная'):
        RearFiveLink(project.front)
    axle = project.rear
    axle.hardpoints.pop('toe_out')
    with pytest.raises(KinematicsError, match='toe_out'):
        RearFiveLink(axle)
    axle = load_template('ring').rear
    p, q = axle.hardpoints['uf_in'], axle.hardpoints['uf_out']
    p.x, p.y, p.z = q.x, q.y, q.z
    with pytest.raises(KinematicsError, match='совпадают'):
        RearFiveLink(axle)
    axle = load_template('ring').rear
    # Duplicate an entire independent constraint: Jacobian cannot have full rank.
    for original, duplicate in (('uf_in', 'ur_in'), ('uf_out', 'ur_out')):
        a, b = axle.hardpoints[original], axle.hardpoints[duplicate]
        b.x, b.y, b.z = a.x, a.y, a.z
    with pytest.raises(KinematicsError, match='вырождена'):
        RearFiveLink(axle)


def test_rear_diagnostic_distinguishes_workspace_from_extended_analysis():
    from suspensionlab.model.validation import validate_axle

    project = load_template('ring')
    rear_keys = {issue.key for issue in validate_axle(project.rear, project)}
    assert 'diag.rear_workspace_solver' in rear_keys
    assert 'diag.no_kinematic_solver' not in rear_keys
    bridge = load_template('live_axle').rear
    assert 'diag.no_kinematic_solver' in {issue.key for issue in validate_axle(bridge)}


def test_failed_rear_branch_and_workspace_never_reuses_poses(monkeypatch):
    original = RearFiveLink._step
    def fail(self, pose, travel):
        if travel > 11:
            raise KinematicsError(travel, 'пробный отказ')
        return original(self, pose, travel)
    monkeypatch.setattr(RearFiveLink, '_step', fail)
    axle = load_template('ring').rear
    result = calculate(axle, -20, 30, 10)
    values = {s.travel_mm: s for s in result.samples}
    assert values[10].scene is not None and values[10].metrics is not None
    assert values[20].scene is None and 'пробный отказ' in values[20].error
    assert values[30].scene is None and 'пробный отказ' in values[30].error
    sweep = limited_sweep(RearFiveLink(axle), [-20, 10, 20, 30])
    assert sweep.reachable_bump_mm <= 11
