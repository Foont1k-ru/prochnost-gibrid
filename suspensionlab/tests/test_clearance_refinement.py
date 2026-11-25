"""Уточнение — ограниченная эвристика, не непрерывная проверка."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from suspensionlab.core.clearance_refinement import _candidate, refine_link_clearance
from suspensionlab.core.kinematics_workspace import calculate
from suspensionlab.core.suspension_clearance import (
    ClearanceSample,
    ClearanceSweep,
    LinkClearance,
    calculate_link_clearance,
)
from suspensionlab.model.templates import load_template


def _synthetic(value, available=True, status=None):
    measurement = SimpleNamespace(clearance_mm=value) if value is not None else None
    pair = LinkClearance('a', 'b', status or ('clear' if measurement else 'unknown_no_pose'), measurement)
    return ClearanceSample(0, (pair,), None if available else 'fail', available)


def _fake_sweep(values, function):
    samples = []
    for value in values:
        sample = function(value)
        samples.append(replace(sample, travel_mm=value))
    return ClearanceSweep(tuple(samples), ('a', 'b'), ())


def test_candidate_detects_measured_failure_boundary_and_threshold():
    a = replace(_synthetic(4), travel_mm=0)
    b = replace(_synthetic(None, status='unknown_geometry'), travel_mm=10)
    assert _candidate(a, b, 0).reason == 'граница доступного расчёта'
    assert _candidate(a, replace(_synthetic(3), travel_mm=10), 3).reason == 'малый зазор или наложение'
    assert _candidate(a, replace(_synthetic(3.001), travel_mm=10), 3) is None
    unknown = replace(_synthetic(None, False), travel_mm=20)
    assert _candidate(unknown, replace(unknown, travel_mm=30), 100) is None
    excluded = replace(_synthetic(None, status='excluded_shared_point'), travel_mm=10)
    assert _candidate(a, excluded, 0) is None


def test_initial_midpoint_discovers_hidden_hit_and_final_pass_recomputed(monkeypatch):
    calls = []
    def fake(*_args, targets=None, **_kwargs):
        values = [-10., 0., 10.] if targets is None else targets
        calls.append(tuple(values))
        # Only the midpoint of the positive initial interval collides.
        return _fake_sweep(values, lambda t: _synthetic(-1. if t == 5 else 10.))
    monkeypatch.setattr('suspensionlab.core.clearance_refinement.calculate_link_clearance', fake)
    report = refine_link_clearance(None, -10, 10, 10, {'a': 1, 'b': 1}, 0, alert_band_mm=0)
    assert report.initial_travels == (-10, 0, 10)
    assert report.added > 2 and report.rounds == 3
    assert 5 in [s.travel_mm for s in report.sweep.samples]
    assert any(s.pairs[0].measurement.clearance_mm == -1 for s in report.sweep.samples)
    assert tuple(s.travel_mm for s in report.sweep.samples) == calls[-1]
    assert report.unresolved and report.limited_by_rounds
    assert not report.unprobed_initial


def test_even_a_midpoint_scan_can_miss_a_narrow_conflict(monkeypatch):
    def fake(*_args, targets=None, **_kwargs):
        values = [-10., 0., 10.] if targets is None else targets
        return _fake_sweep(values, lambda t: _synthetic(-1. if t == 2.5 else 10.))
    monkeypatch.setattr('suspensionlab.core.clearance_refinement.calculate_link_clearance', fake)
    report = refine_link_clearance(None, -10, 10, 10, {'a': 1, 'b': 1}, 0, alert_band_mm=0)
    assert 2.5 not in [s.travel_mm for s in report.sweep.samples]
    assert not report.unresolved  # Not a claim about the unsampled position.


def test_limits_and_inaccessible_intervals_are_reported(monkeypatch):
    def fake(*_args, targets=None, **_kwargs):
        values = [-10., 0., 10.] if targets is None else targets
        return _fake_sweep(values, lambda t: _synthetic(0))
    monkeypatch.setattr('suspensionlab.core.clearance_refinement.calculate_link_clearance', fake)
    budget = refine_link_clearance(None, -10, 10, 10, {'a': 1, 'b': 1}, 0, max_extra=1)
    assert budget.added == 1 and budget.limited_by_budget and len(budget.unprobed_initial) == 1
    minimum = refine_link_clearance(None, -10, 10, 10, {'a': 1, 'b': 1}, 0, min_spacing_mm=5)
    assert minimum.added == 2 and minimum.limited_by_spacing
    assert minimum.rounds == 1 and len(minimum.unresolved) == 4
    zero = refine_link_clearance(None, -10, 10, 10, {'a': 1, 'b': 1}, 0, max_rounds=0)
    assert zero.added == 0 and len(zero.unprobed_initial) == 2 and zero.limited_by_rounds
    unsplit = refine_link_clearance(None, -10, 10, 10, {'a': 1, 'b': 1}, 0, min_spacing_mm=10)
    assert unsplit.added == 0 and unsplit.limited_by_spacing and len(unsplit.unprobed_initial) == 2
    def failures(*_args, targets=None, **_kwargs):
        values = [-10., 0., 10.] if targets is None else targets
        return _fake_sweep(values, lambda t: _synthetic(None, False))
    monkeypatch.setattr('suspensionlab.core.clearance_refinement.calculate_link_clearance', failures)
    report = refine_link_clearance(None, -10, 10, 10, {'a': 1, 'b': 1}, 0)
    assert report.added == 0 and len(report.inaccessible) == 2 and len(report.unprobed_initial) == 2


def test_hard_budget_caps_full_range(monkeypatch):
    def fake(*_args, targets=None, **_kwargs):
        values = list(range(-150, 151, 5)) if targets is None else targets
        return _fake_sweep(values, lambda t: _synthetic(-1))
    monkeypatch.setattr('suspensionlab.core.clearance_refinement.calculate_link_clearance', fake)
    report = refine_link_clearance(None, -150, 150, 5, {'a': 1, 'b': 1}, 0)
    assert len(report.initial_travels) == 61 and report.added == 120
    assert len(report.sweep.samples) == 181 and report.limited_by_budget
    assert report.rounds == 2 and report.unresolved


def test_limited_budget_prioritizes_failure_boundary(monkeypatch):
    def fake(*_args, targets=None, **_kwargs):
        values = [-10., 0., 10.] if targets is None else targets
        return _fake_sweep(values, lambda t: _synthetic(None, False) if t >= 5 else _synthetic(-10))
    monkeypatch.setattr('suspensionlab.core.clearance_refinement.calculate_link_clearance', fake)
    report = refine_link_clearance(None, -10, 10, 10, {'a': 1, 'b': 1}, 0, max_extra=3)
    assert report.added == 3 and report.limited_by_budget
    assert 2.5 in [s.travel_mm for s in report.sweep.samples]
    assert -7.5 not in [s.travel_mm for s in report.sweep.samples]


def test_real_sweep_and_whole_final_grid_matches_fresh_calculation():
    for axle in (load_template('ring').front, load_template('ring').rear):
        radii = ({'lower_arm': 40, 'tierod': 40} if axle.role == 'front' else
                 {'upper_front': 1000, 'toe_link': 1000})
        report = refine_link_clearance(axle, -10, 10, 10, radii, 2, min_spacing_mm=1)
        assert report.added > 2 and report.rounds <= 3
        targets = [s.travel_mm for s in report.sweep.samples]
        assert targets == sorted(set(targets))
        direct = calculate_link_clearance(axle, -10, 10, 10, radii, 2, targets=targets)
        assert direct == report.sweep
        assert all(b - a >= 1 - 1e-12 for a, b in zip(targets, targets[1:], strict=False))


def test_refined_rocker_is_recalculated_with_all_targets():
    from suspensionlab.model.kinematic_elements import KinematicElements, RockerSetup

    axle = load_template('ring').front
    bx, by, bz = axle.hardpoints['lbj'].as_tuple()
    x, y, z = bx + 30., by - 20., bz + 10.
    rocker = RockerSetup(True, 'lower_arm', (x + 100, y + 20, z + 100), (1, 0, 0),
                         (x + 100, y + 70, z + 100), (x, y, z),
                         (x + 100, y + 20, z + 130), (x + 100, y + 100, z + 160))
    axle.kinematic_elements = KinematicElements(axle.type_code, rocker=rocker)
    radii = {'upper_arm': 100, 'rod_capsule': 100, 'damper_capsule': 100}
    report = refine_link_clearance(axle, -10, 10, 10, radii, 0)
    assert report.added > 2
    assert all(p.measurement is not None for s in report.sweep.samples for p in s.pairs)
    targets = [s.travel_mm for s in report.sweep.samples]
    assert calculate_link_clearance(axle, -10, 10, 10, radii, 0, targets=targets) == report.sweep


def test_refines_real_solver_failure_without_extrapolating(monkeypatch):
    from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError

    axle = load_template('ring').front
    step = DoubleWishbone._step
    def fail(self, pose, travel):
        if travel > 3:
            raise KinematicsError(travel, 'тестовый отказ')
        return step(self, pose, travel)
    monkeypatch.setattr(DoubleWishbone, '_step', fail)
    report = refine_link_clearance(axle, 0, 10, 10, {'upper_arm': 5, 'tierod': 5}, 0, alert_band_mm=0)
    samples = report.sweep.samples
    assert any(0 < s.travel_mm < 5 and s.pose_available for s in samples)
    assert all(not s.pose_available for s in samples if s.travel_mm > 3)
    assert any(c.reason == 'граница доступного расчёта' for c in report.unresolved)
    assert report.inaccessible


def test_rejects_bad_refinement_parameters():
    axle = load_template('ring').front
    for kwargs in ({'alert_band_mm': -1}, {'alert_band_mm': float('nan')}, {'min_spacing_mm': 0},
                   {'min_spacing_mm': True}, {'max_extra': 121}, {'max_extra': True}, {'max_rounds': 4}):
        with pytest.raises(ValueError):
            refine_link_clearance(axle, 0, 0, 10, {'upper_arm': 5, 'tierod': 5}, 0, **kwargs)


def test_explicit_targets_require_order_bounds_and_zero():
    axle = load_template('ring').front
    for targets in ([], [-10, 10], [-10, 0, 0, 10], [-10, 1, 0, 10], [-11, 0, 10],
                    [-10, 0, True, 10], [-10, 0, float('nan'), 10]):
        with pytest.raises(ValueError):
            calculate(axle, -10, 10, 10, targets=targets)
    result = calculate(axle, -10, 10, 10, targets=(-10, -2.5, 0, 3.75, 10))
    assert [s.travel_mm for s in result.samples] == [-10, -2.5, 0, 3.75, 10]
    assert all(s.scene is not None for s in result.samples)
