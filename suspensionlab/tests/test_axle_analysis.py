"""Двусторонний свип двухрычажной оси."""
import pytest

from suspensionlab.core.axle_analysis import analyze_symmetric_axle
from suspensionlab.model.templates import load_template


def test_two_sided_sweep_and_mirrored_metrics() -> None:
    project = load_template("ring")
    result = analyze_symmetric_axle(project.front, project.vehicle, [-30, 0, 30], spring_mount="lower_arm")
    assert result.left_scrub.complete_samples and result.right_scrub.complete_samples
    assert result.samples[1].track_change_mm == pytest.approx(0)
    assert result.samples[0].track_mm is not None
    assert result.samples[2].projected_roll_center_z_mm is not None
    for left, right in zip(result.left.samples, result.right.samples, strict=True):
        assert left is not None and right is not None
        assert left.geometry.camber_deg == pytest.approx(right.geometry.camber_deg, abs=1e-7)
        assert left.geometry.scrub_radius_mm == pytest.approx(right.geometry.scrub_radius_mm, abs=1e-7)
        assert left.derivatives.camber_deg_per_25mm == pytest.approx(right.derivatives.camber_deg_per_25mm, abs=1e-7)


def test_unsupported_travel_produces_incomplete_sign_check() -> None:
    project = load_template("ring")
    result = analyze_symmetric_axle(project.front, project.vehicle, [0, 30, 2000])
    assert result.samples[2].track_mm is None
    assert not result.left_scrub.complete_samples
    assert 2000 in result.left_scrub.missing_travel_mm


def test_duplicate_travel_rejected() -> None:
    project = load_template("ring")
    with pytest.raises(ValueError, match="уникальными"):
        analyze_symmetric_axle(project.front, project.vehicle, [0, 0])
