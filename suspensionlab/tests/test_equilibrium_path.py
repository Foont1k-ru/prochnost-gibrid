"""Выборочная проверка пути: сохранение первого отказа и явные ограничения."""
import math
from dataclasses import replace

import numpy as np
import pytest

from suspensionlab.core.equilibrium import EquilibriumPathError, SpringEquilibrium
from suspensionlab.core.spring_characteristics import BumpStopCharacteristic
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize("target", [12.0, -12.0, 0.0])
def test_path_samples_are_ordered_and_limited(target: float) -> None:
    problem = SpringEquilibrium(load_template("ring").front, 230, coil_bind_length_mm=150,
                                damper_mount="lower_arm", damper_limits=StrokeLimits(300, 500))
    path = problem.check_path(target, 1000, step_mm=5)
    assert path.completed and path.failure is None
    assert path.samples[0].travel_mm == 0
    assert path.samples[-1].travel_mm == pytest.approx(target)
    assert path.actual_step_mm <= 5
    assert [p.travel_mm for p in path.samples] == sorted([p.travel_mm for p in path.samples], reverse=target < 0)
    assert "path_sampled_only" in path.limitations
    assert "continuous_reachable_branch_not_guaranteed" in path.limitations
    for p in path.samples:
        assert p.damper is not None and p.damper.stroke is not None and p.damper.stroke.status == "inside"
    if target == 0:
        assert len(path.samples) == 1 and path.actual_step_mm == 0


def test_find_opt_in_path_and_default_are_distinguishable() -> None:
    problem = SpringEquilibrium(load_template("ring").front, 230)
    load = problem.evaluate(12, 1).wheel_support_n
    default = problem.find(load, 0, 20)
    assert default.path is not None and default.path.completed and default.path.actual_step_mm <= 1.0
    disabled = problem.find(load, 0, 20, path_step_mm=None)
    assert disabled.path is None and "equilibrium_path_not_checked" in disabled.limitations
    checked = problem.find(load, 0, 20, path_step_mm=3)
    assert checked.path is not None and checked.path.completed
    assert checked.path.samples[-1].travel_mm == checked.estimate.travel_mm
    assert "path_sampled_only" in checked.limitations
    assert "damper_mount_unspecified" in checked.limitations
    assert "spring_coil_bind_unspecified" in checked.limitations
    assert "bump_stop_not_modeled" in checked.limitations
    for invalid in (0, -1, math.inf, math.nan):
        with pytest.raises(ValueError, match="Шаг"):
            problem.find(load, 0, 20, path_step_mm=invalid)


def test_path_reports_coil_bind_and_bump_stop_with_valid_prefix() -> None:
    axle = load_template("ring").front
    bound = SpringEquilibrium(axle, 230, coil_bind_length_mm=225)
    path = bound.check_path(30, 1000, step_mm=5)
    assert not path.completed and path.failure is not None
    assert path.failure.kind == "component" and "coil_bind" in path.failure.reason
    assert path.samples[0].travel_mm == 0 and path.samples[-1].travel_mm < path.failure.requested_travel_mm
    assert path.failure.requested_travel_mm == path.failure.failure_travel_mm
    stop = SpringEquilibrium(axle, 230, bump_stop=BumpStopCharacteristic(5, 400, 0.5, 5))
    path = stop.check_path(20, 1000, step_mm=5)
    assert path.failure is not None and "bottomed" in path.failure.reason
    assert path.failure.failure_travel_mm == 15
    assert [p.travel_mm for p in path.samples] == [0, 5, 10]


def test_initial_conflict_and_kinematic_failure() -> None:
    axle = load_template("ring").front
    initial = SpringEquilibrium(axle, 230, coil_bind_length_mm=231).check_path(20, 1000, step_mm=5)
    assert initial.failure is not None and initial.failure.failure_travel_mm == 0
    assert initial.samples == ()
    unreachable = SpringEquilibrium(axle, 230).check_path(2000, 1000, step_mm=40)
    assert unreachable.failure is not None and unreachable.failure.kind == "kinematics"
    assert unreachable.failure.failure_travel_mm <= unreachable.failure.requested_travel_mm
    assert len(unreachable.samples) > 0


def test_invalid_and_excessive_path_inputs() -> None:
    problem = SpringEquilibrium(load_template("ring").front, 230)
    for target, load, step in ((math.nan, 100, 1), (0, 0, 1), (0, 100, 0), (0, 100, math.inf),
                               (100, 100, 0.00001), (1e308, 100, 1e-308)):
        with pytest.raises(ValueError):
            problem.check_path(target, load, step_mm=step)


def test_find_rejects_different_branch_at_path_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    problem = SpringEquilibrium(load_template("ring").front, 230)
    load = problem.evaluate(12, 1).wheel_support_n
    original = problem.check_path

    def altered(target_travel_mm: float, load_n: float, *, step_mm: float):
        path = original(target_travel_mm, load_n, step_mm=step_mm)
        endpoint = path.samples[-1]
        assert endpoint.pose is not None
        wrong_pose = replace(endpoint.pose, center=endpoint.pose.center + np.array([1., 0., 0.]))
        return replace(path, samples=(*path.samples[:-1], replace(endpoint, pose=wrong_pose)))

    monkeypatch.setattr(problem, "check_path", altered)
    with pytest.raises(EquilibriumPathError, match="ветвь решения") as exc:
        problem.find(load, 0, 20, path_step_mm=3)
    assert exc.value.path.failure is not None and exc.value.path.failure.kind == "branch_mismatch"
