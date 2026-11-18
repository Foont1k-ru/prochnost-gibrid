"""График сохраняет только фактически полученные точки выборочного пути."""
from dataclasses import replace

import pytest

from suspensionlab.core.equilibrium import PathFailure, SpringEquilibrium
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.core.sweep_plot import PATH_PLOT_METRICS, equilibrium_path_plot_points, plot_segments
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize("target", [-3, 0, 3])
def test_complete_path_plot_preserves_original_order_and_values(target):
    axle = load_template("ring").front
    path = SpringEquilibrium(axle, 230, coil_bind_length_mm=150, damper_mount="lower_arm",
                             damper_limits=StrokeLimits(300, 500)).check_path(target, 1000)
    points = equilibrium_path_plot_points(path)
    assert len(points) == len(path.samples)
    for point, sample in zip(points, path.samples, strict=True):
        assert sample.damper and sample.damper.stroke
        assert point.travel_mm == sample.travel_mm
        assert point.values == (sample.spring.length_mm, sample.spring.coil_clearance_mm, sample.spring.force_n,
                                sample.motion_ratio, sample.wheel_support_n, sample.residual_n,
                                sample.damper.length_mm, sample.damper.stroke.compression_clearance_mm,
                                sample.damper.stroke.extension_clearance_mm)
        assert not point.conflict
    assert len(plot_segments(points, 5, len(PATH_PLOT_METRICS))) == max(0, len(points) - 1)
    assert points[0].travel_mm == 0 and points[-1].travel_mm == target


def test_missing_limits_are_missing_not_zero():
    path = SpringEquilibrium(load_template("ring").front, 230).check_path(-1, 1000)
    for point in equilibrium_path_plot_points(path):
        assert point.values[1] is None and point.values[6:] == (None, None, None)
        assert not point.conflict  # Неизвестные пределы не стали проверенными.


def test_failed_path_has_only_retained_prefix_and_empty_failure_has_no_fake_points():
    axle = load_template("ring").front
    partial = SpringEquilibrium(axle, 230, coil_bind_length_mm=225).check_path(30, 1000, step_mm=5)
    assert partial.failure is not None and partial.samples
    points = equilibrium_path_plot_points(partial)
    assert [p.travel_mm for p in points] == [p.travel_mm for p in partial.samples]
    assert points[-1].travel_mm < partial.failure.failure_travel_mm
    empty = SpringEquilibrium(axle, 230, coil_bind_length_mm=231).check_path(20, 1000)
    assert empty.failure is not None and equilibrium_path_plot_points(empty) == ()


def test_branch_mismatch_marks_endpoint_and_does_not_connect_it():
    path = SpringEquilibrium(load_template("ring").front, 230).check_path(-3, 1000)
    failed = replace(path, failure=PathFailure(-3, -3, "branch_mismatch", "ветви различаются"))
    points = equilibrium_path_plot_points(failed)
    assert len(points) == len(path.samples)
    assert points[-1].conflict and not points[-2].conflict
    assert (len(points) - 2, len(points) - 1) not in plot_segments(points, 5, len(PATH_PLOT_METRICS))
