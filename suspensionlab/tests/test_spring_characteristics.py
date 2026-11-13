"""Физические границы и кусочно-линейная характеристика упругих элементов."""
import pytest

from suspensionlab.core.spring_characteristics import (
    BumpStopCharacteristic,
    SpringCharacteristic,
    bump_stop_state,
    spring_state,
)


def test_linear_loaded_slack_and_contact_boundary() -> None:
    curve = SpringCharacteristic(250, 100)
    loaded = spring_state(curve, 230)
    assert loaded.compression_mm == 20
    assert loaded.force_n == 2000
    assert loaded.tangent_rate_n_mm == 100
    slack = spring_state(curve, 260)
    assert slack.status == "slack" and slack.force_n == 0 and slack.tangent_rate_n_mm == 0
    boundary = spring_state(curve, 250)
    assert boundary.status == "free_boundary" and boundary.tangent_rate_n_mm is None


def test_progressive_force_tangent_knots_and_no_extrapolation() -> None:
    curve = SpringCharacteristic(250, 100, ((0, 0), (10, 100), (20, 300)))
    value = spring_state(curve, 235)
    assert value.force_n == pytest.approx(200)
    assert value.tangent_rate_n_mm == pytest.approx(20)
    knot = spring_state(curve, 240)
    assert knot.force_n == 100 and knot.tangent_rate_n_mm is None
    outside = spring_state(curve, 225)
    assert outside.status == "outside_curve" and outside.force_n is None


def test_coil_bind_is_not_treated_as_valid_force() -> None:
    curve = SpringCharacteristic(250, 100, coil_bind_length_mm=150)
    assert spring_state(curve, 165).coil_clearance_mm == 15
    for length in (150, 140):
        state = spring_state(curve, length)
        assert state.status == "coil_bind" and state.force_n is None and state.tangent_rate_n_mm is None


def test_bump_stop_contact_and_stiffness_at_wheel() -> None:
    stop = BumpStopCharacteristic(40, 400, 0.5, 10)
    assert bump_stop_state(stop, 39).remaining_wheel_travel_mm == 1
    assert bump_stop_state(stop, 40).wheel_rate_n_mm is None
    state = bump_stop_state(stop, 50)
    assert state.compression_mm == pytest.approx(5)
    assert state.force_n == pytest.approx(2000)
    assert state.wheel_force_n == pytest.approx(1000)
    assert state.wheel_rate_n_mm == pytest.approx(100)
    assert bump_stop_state(stop, 60).status == "bottomed"
    assert bump_stop_state(stop, 60).force_n is None


def test_invalid_characteristics() -> None:
    with pytest.raises(ValueError):
        SpringCharacteristic(250, 100, ((0, 1), (10, 100)))
    with pytest.raises(ValueError):
        SpringCharacteristic(250, 100, ((0, 0), (10, 100), (20, 50)))
    with pytest.raises(ValueError):
        SpringCharacteristic(250, 100, coil_bind_length_mm=250)
    with pytest.raises(ValueError):
        bump_stop_state(BumpStopCharacteristic(10, 100, 1), float("nan"))


def test_corner_analysis_does_not_assign_stiffness_to_slack_spring() -> None:
    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.model.templates import load_template

    project = load_template("ring")
    result = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm", static_spring_length_mm=260)
    sample = result.samples[0]
    assert sample is not None and sample.spring is not None and sample.spring.state is not None
    assert sample.spring.state.status == "slack"
    assert sample.spring.wheel_rate_n_mm == 0
    assert sample.spring.frequency_hz is None
    assert "spring_preload_not_applied" in result.limitations


def test_corner_analysis_piecewise_rate_and_coil_bind() -> None:
    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.model.templates import load_template

    project = load_template("ring")
    installed = 235.0
    project.front.spring.free_len_mm = installed + 15
    project.front.spring.progressive = [(0, 0), (10, 100), (20, 300)]
    result = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm", static_spring_length_mm=installed)
    sample = result.samples[0]
    assert sample is not None and sample.spring is not None and sample.spring.state is not None
    assert sample.spring.state.force_n == pytest.approx(200)
    assert sample.spring.state.tangent_rate_n_mm == pytest.approx(20)
    assert sample.spring.wheel_rate_n_mm == pytest.approx(20 * sample.spring.motion_ratio**2)
    bound = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm", coil_bind_length_mm=installed + 1, static_spring_length_mm=installed)
    bound_sample = bound.samples[0]
    assert bound_sample is not None and bound_sample.spring is not None and bound_sample.spring.state is not None
    assert bound_sample.spring.state.status == "coil_bind"
    assert bound_sample.spring.frequency_hz is None


def test_static_spring_length_is_explicit_and_follows_mount_displacement() -> None:
    import numpy as np

    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.core.double_wishbone import DoubleWishbone
    from suspensionlab.core.springs import lower_arm_spring_length
    from suspensionlab.model.templates import load_template

    project = load_template("ring")
    for side, sign in (("left", 1), ("right", -1)):
        model = DoubleWishbone(project.front, side)
        lower = np.array(project.front.hardpoints["spring_lo"].as_tuple()) * [1, sign, 1]
        upper = np.array(project.front.hardpoints["spring_up"].as_tuple()) * [1, sign, 1]
        start = lower_arm_spring_length(model, model.initial_pose(), lower, upper)
        moved = lower_arm_spring_length(model, model.solve(20), lower, upper)
        result = analyze_corner(project.front, project.vehicle, [0, 20], side=side,
                                spring_mount="lower_arm", static_spring_length_mm=230)
        static, bump = result.samples
        assert static is not None and static.spring is not None and static.spring.state is not None
        assert bump is not None and bump.spring is not None and bump.spring.state is not None
        assert static.spring.state.length_mm == pytest.approx(230)
        assert bump.spring.state.length_mm == pytest.approx(230 + moved - start)
        assert "spring_equilibrium_not_checked" in result.limitations
        assert "spring_length_change_equals_mount_distance_change" in result.limitations


def test_unknown_length_progressive_and_invalid_geometry_are_not_guessed() -> None:
    from suspensionlab.core.analysis import analyze_corner
    from suspensionlab.model.templates import load_template

    project = load_template("ring")
    project.front.spring.progressive = [(0, 0), (10, 100)]
    result = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm")
    sample = result.samples[0]
    assert sample is not None and sample.spring is not None
    assert sample.spring.state is None and sample.spring.wheel_rate_n_mm is None
    assert sample.spring.frequency_hz is None
    assert "spring_installed_length_unspecified" in result.limitations
    with pytest.raises(ValueError, match="статическая длина"):
        analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm", coil_bind_length_mm=100)
    with pytest.raises(ValueError):
        analyze_corner(project.front, project.vehicle, [0], static_spring_length_mm=200)
    with pytest.raises(ValueError):
        analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm", static_spring_length_mm=float("nan"))
    invalid = analyze_corner(project.front, project.vehicle, [0, 30], spring_mount="lower_arm", static_spring_length_mm=0.01)
    assert invalid.samples[1] is not None and invalid.samples[1].spring is not None
    assert invalid.samples[1].spring.state is None and invalid.samples[1].spring.error is not None
