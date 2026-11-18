"""Боковая проекция скоростей и размерный контроль оценки антиэффекта."""
from __future__ import annotations

import numpy as np
import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.side_view import (
    SideInstantCenter,
    anti_effect_percent,
    projected_side_instant_center,
    side_force_line_slope,
)
from suspensionlab.model.templates import load_template


def test_side_center_normals_match_numerical_velocities() -> None:
    model = DoubleWishbone(load_template("ring").front)
    for travel in (-20, 0, 20):
        pose = model.solve(travel)
        ic = projected_side_instant_center(model, pose)
        lower, upper = model.sweep([travel - 0.001, travel + 0.001])
        for name in ("ubj", "lbj"):
            p = pose.point(model.points[name], model.center0)
            a = lower.point(model.points[name], model.center0)
            b = upper.point(model.points[name], model.center0)
            velocity = (b - a) / 0.002
            radial = np.array([ic.x - p[0] * ic.w, ic.z - p[2] * ic.w])
            assert abs(np.dot(velocity[[0, 2]], radial)) / np.linalg.norm(radial) < 1e-6


def test_slope_and_antipercent_with_explicit_direction() -> None:
    ic = SideInstantCenter(-1000, 200, 1)
    slope = side_force_line_slope(ic, 0, 0, force_direction_x=-1)
    assert slope == pytest.approx(0.2)
    assert anti_effect_percent(slope, 2500, 500, 0.6) == pytest.approx(60)
    assert side_force_line_slope(ic, 0, 0, force_direction_x=1) == pytest.approx(-0.2)


def test_slope_at_infinity_and_input_validation() -> None:
    ic = SideInstantCenter(1, -0.2, 0)
    assert side_force_line_slope(ic, 50, 0, force_direction_x=1) == pytest.approx(-0.2)
    with pytest.raises(ValueError):
        side_force_line_slope(SideInstantCenter(0, 1, 0), 0, 0, force_direction_x=1)
    with pytest.raises(ValueError):
        anti_effect_percent(0.2, 2500, 0, 0.6)
    with pytest.raises(ValueError):
        anti_effect_percent(0.2, 2500, 500, 1.2)


def test_scenario_is_optional_and_evaluated_with_user_input() -> None:
    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.side_view import LongitudinalScenario

    project = load_template("ring")
    result = analyze_corner(
        project.front, project.vehicle, [-10, 0, 10],
        longitudinal_scenario=LongitudinalScenario(-1, 0.6),
    )
    assert "longitudinal_scenario_unspecified" not in result.limitations
    for sample in result.samples:
        assert sample is not None
        assert sample.side_metrics is not None
        assert sample.side_error is None
        assert sample.side_metrics.anti_percent == pytest.approx(
            anti_effect_percent(sample.side_metrics.force_line_slope, project.vehicle.wheelbase_mm, project.vehicle.cg_height_mm, 0.6)
        )
    incomplete = analyze_corner(project.front, project.vehicle, [0])
    assert "longitudinal_scenario_unspecified" in incomplete.limitations
    assert incomplete.samples[0] is not None and incomplete.samples[0].side_metrics is None
