"""Изолированные условные виды компоновки, без утверждений о реальных размерах."""
import numpy as np
import pytest

from suspensionlab.core.niva_arm_mesh import schematic_mesh
from suspensionlab.model.entities import Project
from suspensionlab.model.niva_arm_views import ARM_KEYS, make_niva_arm_view


def niva():
    project = Project.create_default()
    project.rear.type_code = 'live_axle_coil'
    project.rear.layout = '4link_panhard'
    project.rear.ensure_points(overwrite=True)
    return project


def test_every_arm_available_and_mesh_built_without_modifying_project():
    project = niva()
    before = project.to_dict()
    assert len(ARM_KEYS) == 9
    for key in ARM_KEYS:
        view = make_niva_arm_view(project, key)
        mesh = schematic_mesh(view)
        assert len(view.segments) == (2 if key.startswith('front_') else 1)
        assert len(mesh.triangles) > 100
        assert np.isfinite(mesh.triangles).all()
        assert mesh.triangles.flags.writeable is False
    assert project.to_dict() == before


def test_right_front_mirrors_but_rear_uses_independent_coordinates():
    project = niva()
    left = make_niva_arm_view(project, 'front_upper_left')
    right = make_niva_arm_view(project, 'front_upper_right')
    assert right.points == tuple((x, -y, z) for x, y, z in left.points)
    project.rear.hardpoints['ll_out_r'].x = -777
    right = make_niva_arm_view(project, 'rear_lower_right')
    left = make_niva_arm_view(project, 'rear_lower_left')
    assert right.points[1][0] == -777 and left.points[1][0] != -777
    assert right.joint_kinds == ('bushing', 'bushing')
    assert make_niva_arm_view(project, 'front_lower_left').joint_kinds == ('bushing', 'bushing', 'ball')


def test_rejects_wrong_layout_type_and_degenerate_points():
    project = niva()
    project.rear.layout = '3link_panhard'
    with pytest.raises(ValueError):
        make_niva_arm_view(project, 'rear_upper_left')
    with pytest.raises(ValueError):
        make_niva_arm_view(project, 'panhard')
    project.front.type_code = 'macpherson_front'
    with pytest.raises(ValueError):
        make_niva_arm_view(project, 'front_lower_left')
    project.front.type_code = 'double_wishbone'
    project.front.hardpoints['lbj'].x = float('nan')
    with pytest.raises(ValueError):
        make_niva_arm_view(project, 'front_lower_left')
    project.front.hardpoints.pop('lbj')
    with pytest.raises(ValueError):
        make_niva_arm_view(project, 'front_lower_left')
    with pytest.raises(ValueError):
        make_niva_arm_view(project, 'unknown')
    project = niva()
    p = project.rear.hardpoints['ul_in_l']
    q = project.rear.hardpoints['ul_out_l']
    p.x, p.y, p.z = q.as_tuple()
    with pytest.raises(ValueError):
        make_niva_arm_view(project, 'rear_upper_left')
