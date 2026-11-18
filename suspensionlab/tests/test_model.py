"""Модель данных: точки, рычаги, типы подвесок, автомобиль."""

from __future__ import annotations

import math

import pytest

from suspensionlab.core.geometry import (
    axis_length,
    distance_point_to_line,
    intersect_lines_2d,
    midpoint,
    mirror_y,
)
from suspensionlab.model.entities import (
    Axle,
    Hardpoint,
    Project,
    Wheel,
    parse_tire_size,
    tire_theoretical_radius_mm,
)
from suspensionlab.model.suspension_types import REGISTRY, get_type, types_for_role


def test_registry_contains_required_types() -> None:
    assert set(REGISTRY) == {"macpherson_front", "double_wishbone", "multilink_front", "multilink_rear", "torsion_beam_rear", "live_axle_coil"}
    assert "double_wishbone" in types_for_role("front")
    assert "live_axle_coil" in types_for_role("rear")


def test_default_axle_has_all_points_of_type() -> None:
    axle = Axle(role="front", type_code="double_wishbone")
    axle.ensure_points()
    for spec in get_type("double_wishbone").points:
        assert spec.code in axle.hardpoints
        point = axle.hardpoints[spec.code]
        assert (point.x, point.y, point.z) == (spec.x, spec.y, spec.z)


def test_link_length_uses_pivot_axis() -> None:
    axle = Axle(role="front", type_code="double_wishbone")
    axle.ensure_points()
    upper = axle.hardpoints["ubj"]
    p1 = axle.hardpoints["uca_f_in"]
    p2 = axle.hardpoints["uca_r_in"]
    expected = distance_point_to_line(upper.as_tuple(), p1.as_tuple(), p2.as_tuple())
    assert axle.link_length("upper_arm") == pytest.approx(expected, rel=1e-9)
    assert axle.link_length("upper_arm") > 0


def test_link_angles_are_reported() -> None:
    axle = Axle(role="front", type_code="double_wishbone")
    axle.ensure_points()
    plan, side = axle.link_angles("lower_arm")
    assert -180 <= plan <= 180
    assert -180 <= side <= 180


def test_track_uses_wheel_center() -> None:
    axle = Axle(role="front", type_code="double_wishbone")
    axle.ensure_points()
    assert axle.track_mm() == pytest.approx(2 * axle.hardpoints["wheel_center"].y)


def test_switch_type_keeps_common_points() -> None:
    project = Project.create_default()
    project.front.hardpoints["ubj"].z = 444.0
    project.set_axle_type("front", "multilink_front")
    assert project.front.type_code == "multilink_front"
    assert "l1_in" in project.front.hardpoints
    # при возврате к двухрычажной исходные координаты сохраняются
    project.set_axle_type("front", "double_wishbone")
    assert project.front.hardpoints["ubj"].z == pytest.approx(444.0)


def test_wheel_radius_from_tire_size() -> None:
    assert parse_tire_size("225/45R17") == (225.0, 45.0, 17.0)
    assert parse_tire_size("мусор") is None
    radius = tire_theoretical_radius_mm("225/45R17")
    assert radius == pytest.approx(17 * 25.4 / 2 + 225 * 0.45, rel=1e-9)
    wheel = Wheel(tire="225/45R17", r_dynamic_mm=300.0)
    wheel.sync_from_tire()
    assert wheel.r_dynamic_mm == pytest.approx(radius)


def test_hardpoint_zone_check() -> None:
    point = Hardpoint("ubj", 0.0, 600.0, 400.0, zone_min=(-50, 500, 350), zone_max=(50, 700, 450))
    assert point.in_zone()
    point.z = 460.0
    assert not point.in_zone()


def test_mirror_and_midpoint() -> None:
    assert mirror_y((10.0, 20.0, 30.0)) == (10.0, -20.0, 30.0)
    assert midpoint((0.0, 0.0, 0.0), (10.0, 10.0, 10.0)) == (5.0, 5.0, 5.0)


def test_axis_length_for_two_and_three_points() -> None:
    assert axis_length([(0, 0, 0), (3, 4, 0)]) == pytest.approx(5.0)
    assert axis_length([(0, -5, 0), (0, 5, 0), (10, 0, 0)]) == pytest.approx(10.0)


def test_line_intersection() -> None:
    result = intersect_lines_2d((0.0, 0.0), (10.0, 0.0), (5.0, -5.0), (5.0, 5.0))
    assert result is not None
    assert result[0] == pytest.approx(5.0)
    assert result[1] == pytest.approx(0.0)
    assert intersect_lines_2d((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)) is None


def test_project_clone_is_independent() -> None:
    project = Project.create_default()
    clone = project.clone()
    clone.front.setup.camber_deg = -3.0
    assert project.front.setup.camber_deg != -3.0


def test_project_json_structure(project) -> None:
    data = project.to_dict()
    assert data["schema_version"] == "1.0"
    assert "front_axle" in data and "rear_axle" in data
    assert "hardpoints" in data["front_axle"]
    assert math.isclose(data["vehicle"]["mass_kg"], project.vehicle.mass_kg)


def test_validation_below_ground_does_not_crash(project) -> None:
    from suspensionlab.model.validation import validate_project

    project.front.hardpoints["ubj"].z = -1
    assert any(issue.key == "diag.point_below_ground" for issue in validate_project(project))
