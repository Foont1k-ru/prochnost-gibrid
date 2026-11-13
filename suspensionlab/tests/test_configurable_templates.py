"""Комбинации учебных шаблонов и сохранение реальных типов осей."""
from itertools import product

import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone, KinematicsError
from suspensionlab.i18n import Translator
from suspensionlab.model.project_io import load_project, save_project
from suspensionlab.model.suspension_types import REGISTRY
from suspensionlab.model.templates import VehicleTemplateOptions, create_vehicle_template, list_templates, load_template
from suspensionlab.model.validation import validate_axle


@pytest.mark.parametrize("category,front,rear", [
    (category, front, rear)
    for category, fronts, rears in (
        ("passenger", ("macpherson_front", "multilink_front", "double_wishbone"), ("multilink_rear", "torsion_beam_rear")),
        ("suv", ("multilink_front", "double_wishbone"), ("multilink_rear", "live_axle_coil")),
    ) for front, rear in product(fronts, rears)
])
@pytest.mark.parametrize("front_driven,rear_driven", list(product((False, True), repeat=2)))
def test_combinations_and_round_trip(tmp_path, category, front, rear, front_driven, rear_driven):
    opts = VehicleTemplateOptions(category, front, rear, front_driven, rear_driven)
    if rear == "torsion_beam_rear" and rear_driven:
        with pytest.raises(ValueError):
            create_vehicle_template(opts)
        return
    project = create_vehicle_template(opts)
    assert project.front.type_code == front and project.rear.type_code == rear
    assert project.front.drivetrain.driven == front_driven
    assert project.rear.drivetrain.driven == rear_driven
    for axle in project.axles():
        if axle.drivetrain.driven:
            assert "differential_center" in axle.hardpoints
            assert not any(x.key == "diag.drive_points_missing" for x in validate_axle(axle))
    path = save_project(project, tmp_path / "project")
    restored = load_project(path)
    assert restored.to_dict() == project.to_dict()
    if front != "double_wishbone":
        with pytest.raises((ValueError, KinematicsError)):
            DoubleWishbone(restored.front)


def test_drive_validation_for_live_axle():
    p = create_vehicle_template(VehicleTemplateOptions("suv", "double_wishbone", "live_axle_coil", True, True))
    del p.rear.hardpoints["pinion_center"]
    missing = [dict(issue.params)["code"] for issue in validate_axle(p.rear) if issue.key == "diag.drive_points_missing"]
    assert missing == ["pinion_center"]


def test_invalid_configurations_and_sided_track():
    with pytest.raises(ValueError):
        create_vehicle_template(VehicleTemplateOptions(category="invalid"))
    with pytest.raises(ValueError):
        create_vehicle_template(VehicleTemplateOptions(category="suv"))
    project = create_vehicle_template(VehicleTemplateOptions(rear_type="torsion_beam_rear"))
    assert not project.rear.is_live_axle
    assert project.rear.has_explicit_sides
    project.rear.hardpoints["wheel_center_r"].y = -700
    assert project.rear.track_mm() == pytest.approx(1420)
    assert "strut_top" in project.front.hardpoints and "ubj" not in project.front.hardpoints
    assert "beam_cross_l" in project.rear.hardpoints and "pinion_center" not in project.rear.hardpoints


def test_registry_translations_and_old_templates():
    translator = Translator()
    for spec in REGISTRY.values():
        assert translator.has(spec.name_key) and translator.has(spec.help_key)
        for entry in (*spec.points, *spec.links):
            assert translator.has(entry.name_key), entry.name_key
            assert translator.has(entry.help_key), entry.help_key
    for info in list_templates():
        assert load_template(info.key).path is None
