"""Каркас повторяет расчётную геометрию и не объявляет её пригодной."""
from __future__ import annotations

from dataclasses import replace
from math import atan2, degrees, inf, nan, pi, sqrt

import numpy as np
import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.metrics import _wheel_directions, corner_metrics
from suspensionlab.core.pose_view import pose_view
from suspensionlab.core.scene3d import Scene3D, Segment3D, pose_scene, project_orthographic, scene_bounds
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize("side", ["left", "right"])
def test_segments_follow_same_pose_and_wheel_orientation(side):
    project = load_template("ring")
    axle = project.front
    axle.setup.camber_deg = -3.0
    axle.setup.toe_deg_total = 4.0
    model = DoubleWishbone(axle, side)
    pose = model.solve(10)
    frame = pose_view(model, pose, axle, spring=True, damper=True)
    scene = pose_scene(model, pose, axle, frame)
    assert scene.travel_mm == 10
    assert len(scene.segments) == 82
    assert Segment3D(frame.upper_ball, frame.lower_ball, "knuckle") in scene.segments
    assert Segment3D(*frame.spring, "spring") in scene.segments
    assert Segment3D(*frame.damper, "damper") in scene.segments
    steering = next(segment for segment in scene.segments if segment.kind == "steering")
    assert steering.start == pytest.approx(model.points["tierod_in"])
    assert steering.end == pytest.approx(pose.point(model.points["tierod_out"], model.center0))
    wheel = [segment for segment in scene.segments if segment.kind == "wheel"]
    assert len(wheel) == 72
    normal, forward = _wheel_directions(model, pose, axle.setup.camber_deg, axle.setup.toe_deg_total / 2)
    center = np.array(frame.center)
    expected = center - normal * axle.wheel.width_mm / 2 + forward * axle.wheel.r_dynamic_mm
    assert wheel[0].start == pytest.approx(expected)
    ring_center = np.mean(np.array([segment.start for segment in wheel[:32]]), axis=0)
    assert ring_center == pytest.approx(center - normal * axle.wheel.width_mm / 2, abs=1e-9)
    assert np.linalg.norm(np.array(wheel[0].start) - ring_center) == pytest.approx(axle.wheel.r_dynamic_mm)
    assert np.linalg.norm(np.array(wheel[64].start) - np.array(wheel[64].end)) == pytest.approx(axle.wheel.width_mm)
    cylinder_axis = (np.array(wheel[64].end) - np.array(wheel[64].start)) / axle.wheel.width_mm
    radial_forward = (np.array(wheel[0].start) - ring_center) / axle.wheel.r_dynamic_mm
    metrics = corner_metrics(model, pose, static_camber_deg=axle.setup.camber_deg,
                             static_toe_deg=axle.setup.toe_deg_total / 2)
    assert -degrees(atan2(cylinder_axis[2], model.sign * cylinder_axis[1])) == pytest.approx(metrics.camber_deg)
    assert -model.sign * degrees(atan2(radial_forward[1], radial_forward[0])) == pytest.approx(metrics.toe_deg)


def test_camera_projection_and_shared_bounds():
    assert project_orthographic((3, 4, 5), (1, 2, 3), 0, 0) == pytest.approx((2, 2))
    assert project_orthographic((3, 4, 5), (1, 2, 3), pi / 2, 0) == pytest.approx((2, 2))
    scenes = [Scene3D(0, (Segment3D((0, 0, 0), (2, 4, 6), "arm"),)),
              Scene3D(1, (Segment3D((5, -3, 4), (-2, 4, 3), "wheel"),))]
    bounds = scene_bounds(scenes)
    assert bounds is not None
    center, radius = bounds
    assert scene_bounds([]) is None
    for yaw in (-2, 0, 1, 3):
        for elevation in (-1, 0, 1):
            for scene in scenes:
                for segment in scene.segments:
                    for point in (segment.start, segment.end):
                        x, y = project_orthographic(point, center, yaw, elevation)
                        assert sqrt(x*x + y*y) <= radius + 1e-9
    with pytest.raises(ValueError):
        project_orthographic((inf, 0, 0), center, 0, 0)
    for invalid in (inf, nan):
        with pytest.raises(ValueError):
            scene_bounds([Scene3D(0, (Segment3D((invalid, 0, 0), (1, 0, 0), "arm"),))])


def test_missing_elements_and_invalid_geometry():
    project = load_template("ring")
    model = DoubleWishbone(project.front)
    pose = model.initial_pose()
    frame = pose_view(model, pose, project.front, spring=False, damper=False)
    scene = pose_scene(model, pose, project.front, frame)
    assert len(scene.segments) == 80
    assert all(s.kind not in ("spring", "damper") for s in scene.segments)
    with pytest.raises(ValueError):
        pose_scene(model, pose, project.front, replace(frame, travel_mm=1))
    project.front.wheel.width_mm = 0
    with pytest.raises(ValueError):
        pose_scene(model, pose, project.front, frame)
