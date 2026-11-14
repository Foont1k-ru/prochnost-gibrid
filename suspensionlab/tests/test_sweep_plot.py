"""Проверка данных графика независимо от Qt и округлённой таблицы."""
from dataclasses import replace

import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.damper import LinearDamperCharacteristic, evaluate_linear_damping
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.core.sweep_plot import PLOT_METRICS, PlotPoint, plot_segments, sweep_plot_points
from suspensionlab.model.templates import load_template


def _analysis(**kwargs):
    project = load_template("ring")
    return analyze_corner(project.front, project.vehicle, [-1, 0, 1], **kwargs)


def test_plot_uses_unrounded_values_and_missing_are_not_zero():
    analysis = _analysis()
    points = sweep_plot_points(analysis)
    assert [p.travel_mm for p in points] == [-1, 0, 1]
    for point, sample in zip(points, analysis.samples, strict=True):
        assert sample is not None
        assert point.values[0] == sample.geometry.camber_deg
        assert point.values[1] == sample.geometry.toe_deg
        assert all(value is None for value in point.values[2:])
        assert not point.conflict
    assert plot_segments(points, 0) == ((0, 1), (1, 2))
    assert plot_segments(points, 2) == ()


def test_plot_preserves_spring_and_damping_values_and_conflicts():
    analysis = _analysis(spring_mount="lower_arm", static_spring_length_mm=230,
                         coil_bind_length_mm=150, damper_mount="lower_arm",
                         damper_limits=StrokeLimits(350, 450))
    characteristic = LinearDamperCharacteristic(1.3, 2.4)
    points = sweep_plot_points(analysis, characteristic, 50)
    sample = analysis.samples[1]
    assert sample is not None and sample.spring and sample.spring.state and sample.damper
    dynamics = evaluate_linear_damping(sample.damper, characteristic, 50)
    assert points[1].values[2:7] == (sample.spring.state.length_mm, sample.spring.state.compression_mm,
                                    sample.spring.state.force_n, sample.damper.length_mm, sample.damper.motion_ratio)
    assert points[1].values[7:10] == (dynamics.compression_velocity_mm_s, dynamics.wheel_force_n, dynamics.dissipated_power_w)
    assert not points[1].conflict
    assert sweep_plot_points(analysis)[1].values[7:10] == (None, None, None)
    conflict_spring = replace(sample.spring, state=replace(sample.spring.state, status="coil_bind"))
    broken_damper = replace(sample.damper, error="test")
    altered = replace(analysis, samples=(replace(sample, spring=conflict_spring), None,
                                         replace(sample, damper=broken_damper)))
    altered_points = sweep_plot_points(altered, characteristic, 50)
    assert altered_points[0].conflict and not altered_points[1].conflict and altered_points[2].conflict
    assert all(value is None for value in altered_points[1].values)
    assert altered_points[2].values[7:10] == (None, None, None)
    assert plot_segments(altered_points, 0) == ()


def test_gap_and_detected_conflict_are_never_bridged():
    def point(index, value, conflict=False):
        return PlotPoint(float(index), (value,) + (None,) * (len(PLOT_METRICS) - 1), conflict)
    points = tuple(point(i, value, conflict) for i, (value, conflict) in enumerate([
        (1, False), (2, False), (None, False), (4, False), (5, True), (6, False), (7, False),
        (float("nan"), False), (9, False),
    ]))
    assert plot_segments(points, 0) == ((0, 1), (5, 6))
    with pytest.raises(ValueError):
        plot_segments(points, len(PLOT_METRICS))


def test_missing_and_nonfinite_values_not_invented():
    analysis = _analysis()
    first = analysis.samples[0]
    assert first is not None
    bad = replace(first, geometry=replace(first.geometry, camber_deg=float("nan")))
    result = replace(analysis, samples=(bad, None, analysis.samples[2]))
    points = sweep_plot_points(result)
    assert points[0].values[0] is None and all(v is None for v in points[1].values)
    assert plot_segments(points, 0) == ()
    with pytest.raises(ValueError):
        sweep_plot_points(replace(analysis, samples=analysis.samples[:-1]))


@pytest.mark.parametrize("mode", ["opposed", "bounce"])
def test_antiroll_plot_values_preserve_both_sides_and_left_travel(mode):
    from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
    from suspensionlab.core.sweep_plot import ANTIROLL_METRICS, antiroll_plot_points

    study = AntiRollStudy(load_template("ring").front, AntiRollScenario(-250, 320, 1000))
    sweep = study.sweep_travel(-2, 2, mode=mode)
    points = antiroll_plot_points(sweep.points, [None] * len(sweep.points))
    for point, source in zip(points, sweep.points, strict=True):
        assert source.state is not None
        state = source.state
        assert point.travel_mm == source.left_travel_mm
        assert point.values[:6] == (state.left.arm_angle_deg, state.right.arm_angle_deg, state.twist_deg,
                                state.torque_nm, state.left.compression_force_n, state.right.compression_force_n)
        assert point.values[6:] == (None,) * 10
        assert not point.conflict  # Непроверенные ограничения не превращаются в конфликт или доказательство безопасности.
    assert len(plot_segments(points, 0, len(ANTIROLL_METRICS))) == len(points) - 1


def test_antiroll_conflicts_from_either_side_and_failed_samples():
    from suspensionlab.core.antiroll import AntiRollPoint, AntiRollScenario, AntiRollStudy
    from suspensionlab.core.combined_checks import ComponentChecks, DamperClearance, SpringClearance
    from suspensionlab.core.sweep_plot import ANTIROLL_METRICS, antiroll_plot_points

    study = AntiRollStudy(load_template("ring").front, AntiRollScenario(-250, 320, 1000))
    sweep = study.sweep_travel(-1, 1)
    clear = ComponentChecks(SpringClearance(230, 80, "clear"), DamperClearance(400, None))
    coil_bind = ComponentChecks(SpringClearance(150, 0, "coil_bind"), None)
    invalid_damper = ComponentChecks(None, DamperClearance(0, None, invalid=True))
    points = antiroll_plot_points(sweep.points, [(clear, clear), (clear, coil_bind), (invalid_damper, clear)])
    assert [point.conflict for point in points] == [False, True, True]
    assert plot_segments(points, 2, len(ANTIROLL_METRICS)) == ()
    failure = AntiRollPoint(10, -10, None, "не достигнуто")
    gap = antiroll_plot_points((sweep.points[0], failure, sweep.points[2]), [None, None, None])
    assert gap[1].values == (None,) * len(ANTIROLL_METRICS)
    assert plot_segments(gap, 0, len(ANTIROLL_METRICS)) == ()
    with pytest.raises(ValueError):
        antiroll_plot_points(sweep.points, [None])
    with pytest.raises(ValueError):
        plot_segments(points, 0)  # Нельзя использовать количество колонок другого графика.


def test_corner_plot_clearances_are_signed_and_unknown_is_none():
    result = _analysis(spring_mount="lower_arm", static_spring_length_mm=230,
                       coil_bind_length_mm=231, damper_mount="lower_arm",
                       damper_limits=StrokeLimits(100, 200))
    sample = result.samples[1]
    assert sample and sample.spring and sample.spring.state and sample.damper and sample.damper.stroke
    point = sweep_plot_points(result)[1]
    assert point.conflict
    assert point.values[10:] == (sample.spring.state.coil_clearance_mm,
                                 sample.damper.stroke.compression_clearance_mm,
                                 sample.damper.stroke.extension_clearance_mm)
    assert point.values[10] < 0 and point.values[12] < 0
    without_limits = _analysis(spring_mount="lower_arm", static_spring_length_mm=230,
                               damper_mount="lower_arm")
    assert sweep_plot_points(without_limits)[1].values[10:] == (None, None, None)


def test_antiroll_plot_components_and_unchecked_clearances():
    from suspensionlab.core.antiroll import AntiRollScenario, AntiRollStudy
    from suspensionlab.core.combined_checks import ComponentChecks, DamperClearance, SpringClearance
    from suspensionlab.core.stroke import stroke_state
    from suspensionlab.core.sweep_plot import antiroll_plot_points

    study = AntiRollStudy(load_template("ring").front, AntiRollScenario(-250, 320, 1000))
    result = study.sweep([(0, 0)])
    left = ComponentChecks(SpringClearance(150, 0, "coil_bind"), DamperClearance(300, stroke_state(300, StrokeLimits(350, 450))))
    right = ComponentChecks(SpringClearance(230, None, "limit_unknown"), DamperClearance(400, None))
    point = antiroll_plot_points(result.points, [(left, right)])[0]
    assert point.conflict
    assert point.values[6:] == (150, 230, 0, None, 300, 400, -50, None, 150, None)
    unknown = antiroll_plot_points(result.points, [None])[0]
    assert unknown.values[6:] == (None,) * 10
    assert not unknown.conflict  # Проверок нет, безопасность не установлена.
