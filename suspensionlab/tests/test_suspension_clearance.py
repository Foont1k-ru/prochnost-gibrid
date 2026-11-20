"""Охват дискретных поз и явных ограничений модели капсул."""
from dataclasses import replace
from math import dist

import pytest

from suspensionlab.core.kinematics_workspace import calculate
from suspensionlab.core.segment_clearance import capsule_clearance
from suspensionlab.core.suspension_clearance import calculate_link_clearance
from suspensionlab.model.templates import load_template


def test_front_worst_of_all_arm_branches_and_omissions():
    axle = load_template('ring').front
    sweep = calculate_link_clearance(axle, -10, 10, 10, {'lower_arm': 5, 'tierod': 4}, 2)
    assert sweep.selected == ('lower_arm', 'tierod')
    assert sweep.omitted == ('upper_arm',)
    assert 'wheel' in sweep.not_checked and 'real_parts' in sweep.not_checked
    actual = calculate(axle, -10, 10, 10)
    for sample, pose in zip(sweep.samples, actual.samples, strict=True):
        assert sample.travel_mm == pose.travel_mm
        pair = sample.pairs[0]
        assert pose.scene is not None and pair.measurement is not None
        scene = pose.scene
        expected = [capsule_clearance(scene.point(p), scene.point('lbj'), 5, scene.point('tierod_in'),
                                      scene.point('tierod_out'), 4, 2).clearance_mm
                    for p in ('lca_f_in', 'lca_r_in')]
        assert pair.measurement.clearance_mm == pytest.approx(min(expected))
        assert pair.first_pivot in ('lca_f_in', 'lca_r_in')
        assert pair.second_pivot == 'tierod_in'


def test_rear_explicit_radii_classification_and_range():
    axle = load_template('ring').rear
    options = {'upper_front': 5, 'toe_link': 7, 'lower_rear': 10}
    sweep = calculate_link_clearance(axle, -10, 10, 10, options, 3)
    assert len(sweep.samples) == 3 and len(sweep.samples[0].pairs) == 3
    for sample in sweep.samples:
        for pair in sample.pairs:
            assert pair.measurement is not None
            assert pair.measurement.clearance_mm == pytest.approx(
                dist(pair.measurement.axes.first, pair.measurement.axes.second) - options[pair.first] - options[pair.second])
    very_large = calculate_link_clearance(axle, 0, 0, 10, {'upper_front': 1000, 'toe_link': 1000}, 0)
    assert very_large.samples[0].pairs[0].status == 'overlap'


def test_unsolved_pose_and_missing_or_degenerate_points_are_unknown(monkeypatch):
    axle = load_template('ring').front
    original = calculate(axle, -10, 10, 10)
    scene = original.samples[1].scene
    assert scene is not None
    missing = replace(scene, points=tuple((k, v) for k, v in scene.points if k != 'lbj'))
    duplicate = replace(scene, points=tuple((k, scene.point('lbj') if k == 'lca_f_in' else v)
                                           for k, v in scene.points))
    samples = (replace(original.samples[0], scene=None, error='отказ'),
               replace(original.samples[1], scene=missing), replace(original.samples[2], scene=duplicate))
    monkeypatch.setattr('suspensionlab.core.suspension_clearance.calculate', lambda *_: replace(original, samples=samples))
    sweep = calculate_link_clearance(axle, -10, 10, 10, {'lower_arm': 5, 'tierod': 5}, 0)
    assert [s.pairs[0].status for s in sweep.samples] == ['unknown_no_pose', 'unknown_geometry', 'unknown_geometry']
    assert all(s.pairs[0].measurement is None for s in sweep.samples)
    assert sweep.samples[0].pose_error == 'отказ'


def test_shared_named_joint_excludes_whole_pair_even_if_pose_missing(monkeypatch):
    from types import SimpleNamespace

    axle = load_template('ring').front
    original = calculate(axle, 0, 0, 10)
    spec = SimpleNamespace(link=lambda code: SimpleNamespace(
        pivot=('shared',), end='left' if code == 'upper_arm' else 'right'))
    synthetic = SimpleNamespace(role='front', spec=spec)
    monkeypatch.setattr('suspensionlab.core.suspension_clearance.supported', lambda _: True)
    monkeypatch.setattr('suspensionlab.core.suspension_clearance.calculate',
                        lambda *_: replace(original, samples=(replace(original.samples[0], scene=None),)))
    result = calculate_link_clearance(synthetic, 0, 0, 10, {'upper_arm': 5, 'lower_arm': 5}, 0)
    pair = result.samples[0].pairs[0]
    assert pair.status == 'excluded_shared_point' and pair.measurement is None


def test_unsupported_bad_inputs_and_no_implicit_sizes():
    axle = load_template('ring').front
    for choices in ({}, {'upper_arm': 5}, {'upper_arm': 5, 'wheel': 5},
                    {'upper_arm': 0, 'tierod': 5}, {'upper_arm': True, 'tierod': 5}):
        with pytest.raises(ValueError):
            calculate_link_clearance(axle, 0, 0, 10, choices, 0)
    for margin in (-1, float('nan'), True):
        with pytest.raises(ValueError):
            calculate_link_clearance(axle, 0, 0, 10, {'upper_arm': 5, 'tierod': 5}, margin)
    axle.type_code = 'macpherson'
    with pytest.raises(ValueError):
        calculate_link_clearance(axle, 0, 0, 10, {'upper_arm': 5, 'tierod': 5}, 0)
