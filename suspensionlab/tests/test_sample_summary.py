"""Группировка по рассчитанным точкам не является классификацией промежутков."""
from dataclasses import replace
from math import nan

import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
from suspensionlab.core.combined_checks import ComponentChecks, DamperClearance, SpringClearance
from suspensionlab.core.sample_summary import (
    SampleCheck,
    antiroll_status,
    antiroll_summary,
    corner_status,
    corner_summary,
    group_samples,
)
from suspensionlab.core.stroke import StrokeLimits, stroke_state
from suspensionlab.model.templates import load_template


def corner(**kwargs):
    project = load_template("ring")
    return analyze_corner(project.front, project.vehicle, [-1, 0, 1], **kwargs)


def test_corner_unknowns_known_limits_and_conflict_priority():
    base = corner()
    assert all(point.status == "incomplete" for point in corner_summary(base))
    known = corner(spring_mount="lower_arm", static_spring_length_mm=230, coil_bind_length_mm=150,
                   damper_mount="lower_arm", damper_limits=StrokeLimits(350, 450))
    sample = known.samples[1]
    assert sample is not None and sample.spring is not None and sample.spring.state is not None and sample.damper is not None
    assert all(point.status == "checked" for point in corner_summary(known))
    from suspensionlab.core.sweep_plot import sweep_plot_points
    conflict_result = corner(spring_mount="lower_arm", static_spring_length_mm=230, coil_bind_length_mm=230,
                             damper_mount="lower_arm", damper_limits=StrokeLimits(350, 450))
    assert [point.status == "conflict" for point in corner_summary(conflict_result)] == [
        point.conflict for point in sweep_plot_points(conflict_result)
    ]
    assert corner_status(None) == "unavailable"
    assert corner_status(replace(sample, spring=None)) == "incomplete"
    assert corner_status(replace(sample, damper=None)) == "incomplete"
    assert corner_status(replace(sample, damper=replace(sample.damper, stroke=None))) == "incomplete"
    assert corner_status(replace(sample, spring=replace(sample.spring, state=replace(sample.spring.state, force_n=None)))) == "incomplete"
    coil = replace(sample.spring, state=replace(sample.spring.state, status="coil_bind"))
    assert corner_status(replace(sample, spring=coil, damper=None)) == "conflict"
    assert corner_status(replace(sample, spring=None, damper=replace(sample.damper, error="error"))) == "conflict"
    assert corner_status(replace(sample, spring=replace(sample.spring, error="error"))) == "conflict"
    with pytest.raises(ValueError):
        corner_summary(replace(known, samples=known.samples[:-1]))


def test_antiroll_uses_both_sides_and_does_not_imply_safety():
    study = AntiRollStudy(load_template("ring").front, AntiRollScenario(-250, 320, 1000))
    result = study.sweep([(-1, 1), (0, 0), (1, -1)])
    clear = ComponentChecks(SpringClearance(230, 80, "clear"), DamperClearance(400, stroke_state(400, StrokeLimits(350, 450))))
    unknown = ComponentChecks(SpringClearance(230, None, "limit_unknown"), DamperClearance(400, None))
    conflict = ComponentChecks(SpringClearance(150, 0, "coil_bind"), None)
    damper_bad = ComponentChecks(None, DamperClearance(0, None, True))
    assert antiroll_status(result.points[0], None) == "incomplete"
    assert antiroll_status(result.points[0], (clear, clear)) == "checked"
    assert antiroll_status(result.points[0], (clear, unknown)) == "incomplete"
    assert antiroll_status(result.points[0], (unknown, conflict)) == "conflict"
    assert antiroll_status(result.points[0], (damper_bad, clear)) == "conflict"
    assert antiroll_status(replace(result.points[0], state=None), (conflict, clear)) == "unavailable"
    samples = antiroll_summary(result.points, [(clear, clear), None, (clear, conflict)])
    assert [p.status for p in samples] == ["checked", "incomplete", "conflict"]
    assert [p.travel_mm for p in samples] == [-1, 0, 1]
    assert [p.right_travel_mm for p in samples] == [1, 0, -1]
    with pytest.raises(ValueError):
        antiroll_summary(result.points, [None])


def test_groups_preserve_order_exact_endpoints_and_do_not_merge_separated_runs():
    samples = (SampleCheck(2, "checked", -2), SampleCheck(1, "checked", -1),
               SampleCheck(0, "conflict", 0), SampleCheck(-1, "checked", 1),
               SampleCheck(-2, "unavailable", 2), SampleCheck(-3, "unavailable", 3))
    groups = group_samples(samples)
    assert [(g.first_row, g.last_row, g.count, g.first.status) for g in groups] == [
        (0, 1, 2, "checked"), (2, 2, 1, "conflict"), (3, 3, 1, "checked"), (4, 5, 2, "unavailable"),
    ]
    assert groups[0].first.travel_mm == 2 and groups[0].last.travel_mm == 1
    assert groups[0].first.right_travel_mm == -2 and groups[0].last.right_travel_mm == -1
    assert group_samples(()) == ()
    with pytest.raises(ValueError):
        group_samples((SampleCheck(nan, "incomplete"),))
    with pytest.raises(ValueError):
        group_samples((SampleCheck(0, "checked", nan),))
