"""Предупреждения о выбранной условной топологии, не инженерная проверка."""
from __future__ import annotations

import pytest

from suspensionlab.core.powertrain_layout import layout_diagram, layout_topology_status
from suspensionlab.i18n import Translator
from suspensionlab.model.templates import VehicleTemplateOptions, create_vehicle_template
from suspensionlab.model.validation import validate_axle, validate_project


def make_project(layout: str, front: bool, rear: bool):
    project = create_vehicle_template(VehicleTemplateOptions("suv", "double_wishbone", "live_axle_coil",
                                                             front, rear))
    project.vehicle.powertrain_layout = layout
    return project


@pytest.mark.parametrize("layout,front,rear,status", [
    ("unspecified", True, False, "unspecified"),
    ("transverse_front", False, True, "incompatible"),
    ("longitudinal_transaxle", False, True, "incompatible"),
    ("longitudinal_transfer", False, True, "ok"),
    ("transverse_front", True, True, "ok"),
    ("new_unknown_layout", True, True, "unsupported"),
])
def test_diagram_and_project_diagnostics_share_topology_rules(layout, front, rear, status):
    project = make_project(layout, front, rear)
    assert layout_topology_status(layout, front, rear) == layout_diagram(project).status == status
    issues = [issue for issue in validate_project(project) if issue.key.startswith("diag.powertrain_")]
    if status == "ok":
        assert not issues
    else:
        assert len(issues) == 1 and issues[0].key == f"diag.powertrain_{status}"
        assert issues[0].severity == ("info" if status == "unspecified" else "warning")
        assert Translator().has(issues[0].key)
        assert not issues[0].role  # Настройка относится к автомобилю, не отдельной оси.


def test_no_unconfigured_powertrain_notice_without_driven_axles():
    project = make_project("unspecified", False, False)
    assert not any(issue.key.startswith("diag.powertrain_") for issue in validate_project(project))


def test_invalid_data_is_reported_without_inventing_geometry():
    project = make_project("longitudinal_transfer", True, True)
    project.vehicle.wheelbase_mm = float("nan")
    assert layout_diagram(project).status == "invalid"
    assert any(issue.key == "diag.powertrain_invalid" for issue in validate_project(project))
    project.vehicle.wheelbase_mm = 2650
    del project.front.hardpoints["differential_center"]
    assert any(issue.key == "diag.powertrain_invalid" for issue in validate_project(project))


@pytest.mark.parametrize("role", ["front", "rear"])
def test_unused_legacy_cardan_point_does_not_create_geometry_errors(role):
    project = make_project("longitudinal_transfer", True, True)
    axle = project.axle(role)
    legacy = axle.hardpoints["driveshaft_front"]
    differential = axle.hardpoints["differential_center"]
    legacy.x, legacy.y, legacy.z = differential.x, differential.y, differential.z
    issues = validate_axle(axle, project)
    assert not any(issue.key == "diag.points_coincide" and "driveshaft_front" in str(issue.params) for issue in issues)
    assert not any(issue.key == "diag.link_too_short" and issue.code in ("driveshaft", "driveshaft_to_differential") for issue in issues)
    del axle.hardpoints["driveshaft_front"]
    issues = validate_axle(axle, project)
    assert not any(issue.key in ("diag.point_missing", "diag.drive_points_missing") and
                   (issue.code == "driveshaft_front" or ("code", "driveshaft_front") in issue.params) for issue in issues)
    assert layout_diagram(project).status == "ok"
