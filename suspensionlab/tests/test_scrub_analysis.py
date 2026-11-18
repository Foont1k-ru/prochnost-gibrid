"""Проверки смены знака плеча обкатки, пропусков и граничных случаев."""
import pytest

from suspensionlab.core.scrub_analysis import check_scrub_signs


def test_sign_change_and_interpolation() -> None:
    result = check_scrub_signs([(25, 2), (-25, -4), (0, -1)])
    assert result.complete_samples
    assert result.sign_change_detected
    change = result.changes[0]
    assert (change.from_travel_mm, change.to_travel_mm) == (0, 25)
    assert change.estimated_zero_mm == pytest.approx(25 / 3)


def test_zero_and_multiple_changes() -> None:
    result = check_scrub_signs([(-2, 2), (-1, 0), (0, -2), (1, 0), (2, 2)])
    assert result.near_zero_travel_mm == (-1, 1)
    assert len(result.changes) == 2


def test_gap_is_not_bridged() -> None:
    result = check_scrub_signs([(-10, -2), (0, None), (10, 2)])
    assert result.missing_travel_mm == (0,)
    assert not result.complete_samples
    assert not result.sign_change_detected


def test_no_samples_is_incomplete_and_touch_is_not_sign_change() -> None:
    assert not check_scrub_signs([]).complete_samples
    result = check_scrub_signs([(-1, 2), (0, 0), (1, 3)])
    assert result.near_zero_travel_mm == (0,)
    assert not result.sign_change_detected


def test_bad_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        check_scrub_signs([(0, 1), (0, 2)])
    with pytest.raises(ValueError):
        check_scrub_signs([(0, float("nan"))])
    with pytest.raises(ValueError):
        check_scrub_signs([(0, 1)], zero_tolerance_mm=-1)


def test_refine_on_real_double_wishbone_both_sides() -> None:
    from suspensionlab.core.double_wishbone import DoubleWishbone
    from suspensionlab.core.metrics import corner_metrics
    from suspensionlab.core.scrub_analysis import refine_scrub_sign_change
    from suspensionlab.model.templates import load_template

    axle = load_template("ring").front
    axle.hardpoints["wheel_center"].y = 708
    roots = []
    for side in ("left", "right"):
        model = DoubleWishbone(axle, side)
        result = refine_scrub_sign_change(model, -30, 30, travel_tolerance_mm=0.001)
        assert result.to_travel_mm - result.from_travel_mm <= 0.001
        assert result.from_value_mm * result.to_value_mm <= 0
        value = corner_metrics(model, model.solve(result.estimated_zero_mm)).scrub_radius_mm
        assert abs(value) < 0.001
        roots.append(result.estimated_zero_mm)
    assert roots[0] == pytest.approx(roots[1], abs=1e-9)


def test_refinement_rejects_invalid_bracket() -> None:
    from suspensionlab.core.double_wishbone import DoubleWishbone
    from suspensionlab.core.scrub_analysis import refine_scrub_sign_change
    from suspensionlab.model.templates import load_template

    model = DoubleWishbone(load_template("ring").front)
    with pytest.raises(ValueError, match="разные знаки"):
        refine_scrub_sign_change(model, 0, 20)
    with pytest.raises(ValueError, match="возрастать"):
        refine_scrub_sign_change(model, 10, -10)
