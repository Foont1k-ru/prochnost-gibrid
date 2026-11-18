"""Точки и границы условного 3D-каркаса целого проекта."""
from copy import deepcopy

import pytest

from suspensionlab.core.vehicle_schematic_scene import vehicle_schematic_scene
from suspensionlab.model.templates import list_templates, load_template


@pytest.mark.parametrize('key', [info.key for info in list_templates()])
def test_packaged_templates_have_two_axles_and_do_not_change_project(key):
    project = load_template(key)
    before = deepcopy(project.to_dict())
    result = vehicle_schematic_scene(project)
    assert result.scene.segments and not result.missing
    for axle in (project.front, project.rear):
        for side, suffix, sign in [('left', '_l', 1), ('right', '_r', -1)]:
            code = 'wheel_center' + (suffix if axle.has_explicit_sides else '')
            local = axle.hardpoints[code]
            name = f'{axle.role}:{code}:{side}'
            assert result.scene.point(name) == (
                local.x - (project.vehicle.wheelbase_mm if axle.role == 'rear' else 0),
                local.y if axle.has_explicit_sides else local.y * sign,
                local.z,
            )
    assert project.to_dict() == before


def test_explicit_sides_not_mirrored_and_missing_points_are_reported():
    project = load_template('live_axle')
    rear = project.rear
    rear.hardpoints['wheel_center_r'].y = -912
    result = vehicle_schematic_scene(project)
    assert result.scene.point('rear:wheel_center_r:right')[1] == -912
    del rear.hardpoints['wheel_center_r']
    incomplete = vehicle_schematic_scene(project)
    assert any(s.startswith('rear:wheel_center_r') for s in incomplete.missing)
    assert len(incomplete.scene.segments) < len(result.scene.segments)


@pytest.mark.parametrize('field,value', [('wheelbase_mm', 0), ('wheelbase_mm', float('nan')), ('wheelbase_mm', 1e99)])
def test_invalid_wheelbase_is_not_silently_drawn(field, value):
    project = load_template('ring')
    setattr(project.vehicle, field, value)
    with pytest.raises(ValueError):
        vehicle_schematic_scene(project)


def test_invalid_point_and_wheel_fail_closed():
    project = load_template('city')
    project.front.hardpoints['wheel_center'].x = float('inf')
    with pytest.raises(ValueError):
        vehicle_schematic_scene(project)
    project = load_template('city')
    project.rear.wheel.width_mm = -1
    with pytest.raises(ValueError):
        vehicle_schematic_scene(project)
