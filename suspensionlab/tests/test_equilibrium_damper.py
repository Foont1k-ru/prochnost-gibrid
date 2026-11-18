"""Физическая проверка упоров в найденных точках равновесия."""
import math

import numpy as np
import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.equilibrium import EquilibriumError, SpringEquilibrium, estimate_spring_support_tangent
from suspensionlab.core.springs import lower_arm_spring_length
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.model.templates import load_template


def initial_damper_length() -> float:
    axle = load_template("ring").front
    model = DoubleWishbone(axle)
    return lower_arm_spring_length(model, model.initial_pose(),
                                  np.array(axle.hardpoints["damper_lo"].as_tuple()),
                                  np.array(axle.hardpoints["damper_up"].as_tuple()))


@pytest.mark.parametrize("side", ["left", "right"])
def test_valid_equilibrium_checks_damper_and_matches_corner(side: str) -> None:
    project = load_template("ring")
    limits = StrokeLimits(300, 500)
    problem = SpringEquilibrium(project.front, 230, side=side, damper_mount="lower_arm", damper_limits=limits)
    load = problem.evaluate(12, 1).wheel_support_n
    result = problem.find(load, 0, 20, travel_tolerance_mm=0.001)
    assert result.estimate.travel_mm == pytest.approx(12, abs=0.001)
    assert "damper_limits_discrete_only" in result.limitations
    assert result.lower.damper is not None and result.lower.damper.stroke is not None
    assert result.upper.damper is not None and result.upper.damper.stroke is not None
    assert result.estimate.damper is not None and result.estimate.damper.stroke is not None
    assert all(p.damper is not None and p.damper.stroke is not None and p.damper.stroke.status == "inside"
               for p in (result.lower, result.upper, result.estimate))
    corner = analyze_corner(project.front, project.vehicle, [result.estimate.travel_mm], side=side,
                            spring_mount="lower_arm", static_spring_length_mm=230,
                            damper_mount="lower_arm", damper_limits=limits).samples[0]
    assert corner is not None and corner.damper is not None
    assert result.estimate.damper.length_mm == pytest.approx(corner.damper.length_mm, abs=1e-8)


def test_up_against_stop_or_beyond_is_not_accepted() -> None:
    axle = load_template("ring").front
    length = initial_damper_length()
    system = SpringEquilibrium(axle, 230, damper_mount="lower_arm", damper_limits=StrokeLimits(length, length + 10))
    with pytest.raises(EquilibriumError, match="compressed_limit") as exc:
        system.evaluate(0, 100)
    assert exc.value.travel_mm == 0
    with pytest.raises(EquilibriumError, match="below_compressed"):
        system.evaluate(20, 100)
    with pytest.raises(EquilibriumError, match="above_extended"):
        system.evaluate(-30, 100)
    with pytest.raises(EquilibriumError, match="compressed_limit"):
        system.find(1000, 0, 20)
    with pytest.raises(EquilibriumError):
        estimate_spring_support_tangent(system, 0)


def test_absent_or_unconfigured_limits_are_never_claimed_as_verified() -> None:
    axle = load_template("ring").front
    plain = SpringEquilibrium(axle, 230)
    assert plain.evaluate(0, 100).damper is None
    assert "damper_mount_unspecified" in plain.limitations
    unbounded = SpringEquilibrium(axle, 230, damper_mount="lower_arm")
    point = unbounded.evaluate(0, 100)
    assert point.damper is not None and point.damper.stroke is None
    assert "damper_limits_unspecified" in unbounded.limitations
    assert "damper_limits_discrete_only" not in unbounded.limitations
    with pytest.raises(ValueError, match="крепление"):
        SpringEquilibrium(axle, 230, damper_limits=StrokeLimits(300, 500))
    axle.hardpoints["damper_up"].x = math.nan
    with pytest.raises(ValueError, match="конечными"):
        SpringEquilibrium(axle, 230, damper_mount="lower_arm")
