"""Компоновочные схемы — только графические учебные допущения."""
from __future__ import annotations

from itertools import product

import pytest

from suspensionlab.core.powertrain_layout import LAYOUTS, layout_diagram
from suspensionlab.core.wheel_projection import wheel_projection
from suspensionlab.model.project_io import load_project, save_project
from suspensionlab.model.snapshot_restore import prepare_snapshot
from suspensionlab.model.templates import VehicleTemplateOptions, create_vehicle_template, load_template


@pytest.mark.parametrize("layout", LAYOUTS[1:])
@pytest.mark.parametrize("front,rear", list(product([False, True], repeat=2)))
def test_layout_topology_is_explicit_and_depends_on_driven_axles(layout: str, front: bool, rear: bool) -> None:
    project = create_vehicle_template(VehicleTemplateOptions("passenger", "double_wishbone", "multilink_rear",
                                                             front, rear, layout))
    before = project.to_dict()
    diagram = layout_diagram(project)
    if layout != "longitudinal_transfer" and rear and not front:
        assert diagram.status == "incompatible" and not diagram.components and not diagram.shafts
    else:
        assert diagram.status == "ok"
        roles = {shaft.role for shaft in diagram.shafts}
        assert ("front" in roles) == (layout == "longitudinal_transfer" and front)
        assert ("rear" in roles) == rear
        assert {part.kind for part in diagram.components} >= {"engine"}
        if layout == "longitudinal_transfer":
            assert "transfer" in {part.kind for part in diagram.components}
    assert project.to_dict() == before  # Схема не меняет точки и не подменяет данные.


@pytest.mark.parametrize("rear_type", ["multilink_rear", "live_axle_coil"])
def test_transfer_case_connects_correct_sides_of_vehicle(rear_type: str) -> None:
    category = "suv" if rear_type == "live_axle_coil" else "passenger"
    project = create_vehicle_template(VehicleTemplateOptions(category, "double_wishbone", rear_type,
                                                             True, True, "longitudinal_transfer"))
    project.vehicle.wheelbase_mm = 2800
    project.front.hardpoints["differential_center"].x = 50
    rear_code = "pinion_center" if project.rear.is_live_axle else "differential_center"
    project.rear.hardpoints[rear_code].x = 70
    diagram = layout_diagram(project)
    shafts = {shaft.role: shaft for shaft in diagram.shafts}
    assert set(shafts) == {"front", "rear"}
    assert shafts["front"].start == shafts["rear"].start
    assert shafts["rear"].end[0] == -2800 + 70
    assert shafts["front"].end[0] == 50
    assert shafts["rear"].end[0] < shafts["front"].start[0] < shafts["front"].end[0]
    assert diagram.status == "ok"


@pytest.mark.parametrize("layout", ["transverse_front", "longitudinal_transaxle"])
def test_front_transaxle_sends_one_shaft_rearward_only_when_awd(layout: str) -> None:
    project = create_vehicle_template(VehicleTemplateOptions("passenger", "double_wishbone", "multilink_rear",
                                                             True, True, layout))
    shaft, = layout_diagram(project).shafts
    assert shaft.role == "rear" and shaft.start[0] > shaft.end[0]
    project.rear.drivetrain.driven = False
    assert not layout_diagram(project).shafts


def test_legacy_project_and_snapshot_do_not_gain_layout_or_move_points(tmp_path) -> None:
    project = load_template("ring")
    original = project.to_dict()
    assert "powertrain_layout" not in original["vehicle"]
    assert layout_diagram(project).status == "unspecified"
    assert not layout_diagram(project).shafts
    path = save_project(project, tmp_path / "old")
    loaded = load_project(path, require_complete=True)
    assert loaded.to_dict() == original
    assert prepare_snapshot(original).to_dict()["vehicle"] == original["vehicle"]
    assert loaded.front.hardpoints["driveshaft_front"].as_tuple() == project.front.hardpoints["driveshaft_front"].as_tuple()


@pytest.mark.parametrize("layout", LAYOUTS[1:])
def test_layout_persists_in_project_and_snapshot(tmp_path, layout: str) -> None:
    project = create_vehicle_template(VehicleTemplateOptions("suv", "double_wishbone", "live_axle_coil",
                                                             True, True, layout))
    path = save_project(project, tmp_path / "new")
    restored = load_project(path, require_complete=True)
    assert restored.vehicle.powertrain_layout == layout
    assert layout_diagram(restored) == layout_diagram(project)
    assert prepare_snapshot(project.to_dict()).vehicle.powertrain_layout == layout


def test_unknown_or_incomplete_layout_never_guesses_shaft() -> None:
    project = load_template("ring")
    project.vehicle.powertrain_layout = "future_layout"
    assert layout_diagram(project).status == "unsupported"
    project.vehicle.powertrain_layout = "longitudinal_transfer"
    project.vehicle.wheelbase_mm = float("nan")
    assert layout_diagram(project).status == "invalid"
    project.vehicle.wheelbase_mm = 2650
    project.front.drivetrain.driven = True
    del project.front.hardpoints["differential_center"]
    assert layout_diagram(project).status == "invalid"
    with pytest.raises(ValueError, match="powertrain"):
        create_vehicle_template(VehicleTemplateOptions(powertrain_layout="wrong"))


@pytest.mark.parametrize("mode,shape,half_u,half_v", [
    ("front", "rectangle", 100, 300), ("side", "ellipse", 300, 300), ("top", "rectangle", 300, 100),
])
def test_wheel_projection_dimensions(mode: str, shape: str, half_u: float, half_v: float) -> None:
    assert wheel_projection(mode, 300, 200) == (shape, half_u, half_v)
