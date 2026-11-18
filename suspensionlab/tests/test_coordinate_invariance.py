"""Метаморфные проверки координат: не физическая валидация подвески."""
from __future__ import annotations

import copy
from math import cos, radians, sin

import numpy as np
import pytest

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.equilibrium import SpringEquilibrium
from suspensionlab.core.metrics import corner_derivatives, corner_metrics
from suspensionlab.core.screw_axis import instantaneous_motion
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.model.entities import Axle
from suspensionlab.model.templates import load_template


def make_geometry(case: int) -> Axle:
    axle = load_template("ring").front
    offsets = {
        0: {},
        1: {"uca_f_in": (6, -5, 4), "ubj": (5, -6, 3), "lbj": (4, 5, -3),
            "tierod_out": (8, -4, 5), "spring_lo": (7, -4, 5)},
        2: {"uca_r_in": (7, -8, 5), "ubj": (-8, 6, -4), "lca_r_in": (4, 7, 6),
            "lbj": (-6, -5, 4), "tierod_in": (-7, 5, 3), "damper_lo": (-4, 5, -3)},
    }
    for name, (dx, dy, dz) in offsets[case].items():
        point = axle.hardpoints[name]
        point.x += dx
        point.y += dy
        point.z += dz
    return axle


def transform_axle(axle: Axle, yaw_deg: float, translation: tuple[float, float, float]) -> tuple[Axle, np.ndarray]:
    """Поворачивает все заданные точки вокруг Z и затем переносит их."""
    angle = radians(yaw_deg)
    rotation = np.array([[cos(angle), -sin(angle), 0], [sin(angle), cos(angle), 0], [0, 0, 1]])
    transformed = copy.deepcopy(axle)
    for point in transformed.hardpoints.values():
        xyz = rotation @ np.array(point.as_tuple()) + np.array(translation)
        point.x, point.y, point.z = (float(value) for value in xyz)
    return transformed, rotation


@pytest.mark.parametrize("case", [0, 1, 2])
@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("travel", [-20.0, 0.0, 20.0])
@pytest.mark.parametrize("yaw,translation", [
    (0.0, (220.0, -170.0, 120.0)),
    (35.0, (0.0, 0.0, 0.0)),
    (-70.0, (125.0, -85.0, 160.0)),
])
def test_rigid_frame_changes_preserve_3d_pose_and_component_behavior(
    case: int, side: str, travel: float, yaw: float, translation: tuple[float, float, float],
) -> None:
    axle = make_geometry(case)
    transformed, q = transform_axle(axle, yaw, translation)
    # Правая сторона получается отражением Y до и после преобразования.
    mirror = np.diag([1.0, -1.0 if side == "right" else 1.0, 1.0])
    side_rotation = mirror @ q @ mirror
    side_translation = mirror @ np.array(translation)
    limits = StrokeLimits(300, 500)
    def make_system(a: Axle) -> SpringEquilibrium:
        return SpringEquilibrium(a, 230, side=side, coil_bind_length_mm=150,
                                 damper_mount="lower_arm", damper_limits=limits)
    original, rotated = make_system(axle), make_system(transformed)
    a, b = original.evaluate(travel, 1000), rotated.evaluate(travel, 1000)
    assert a.pose is not None and b.pose is not None
    np.testing.assert_allclose(b.pose.center, side_rotation @ a.pose.center + side_translation, atol=2e-6, rtol=0)
    np.testing.assert_allclose(b.pose.rotation, side_rotation @ a.pose.rotation @ side_rotation.T, atol=2e-8, rtol=0)
    for name in ("ubj", "lbj", "tierod_out"):
        start = a.pose.point(original.model.points[name], original.model.center0)
        end = b.pose.point(rotated.model.points[name], rotated.model.center0)
        np.testing.assert_allclose(end, side_rotation @ start + side_translation, atol=2e-6, rtol=0)
    v1, v2 = instantaneous_motion(original.model, a.pose), instantaneous_motion(rotated.model, b.pose)
    np.testing.assert_allclose(v2.linear, side_rotation @ v1.linear, atol=2e-8, rtol=0)
    np.testing.assert_allclose(v2.angular, side_rotation @ v1.angular, atol=2e-8, rtol=0)
    assert b.spring.status == a.spring.status
    assert b.spring.length_mm == pytest.approx(a.spring.length_mm, abs=2e-6, rel=0)
    assert b.spring.coil_clearance_mm == pytest.approx(a.spring.coil_clearance_mm, abs=2e-6, rel=0)
    assert b.spring.force_n == pytest.approx(a.spring.force_n, abs=2e-4, rel=0)
    assert b.motion_ratio == pytest.approx(a.motion_ratio, abs=2e-8, rel=0)
    assert b.wheel_support_n == pytest.approx(a.wheel_support_n, abs=2e-4, rel=0)
    assert b.residual_n == pytest.approx(a.residual_n, abs=2e-4, rel=0)
    assert a.damper is not None and b.damper is not None
    assert a.damper.stroke is not None and b.damper.stroke is not None
    assert b.damper.length_mm == pytest.approx(a.damper.length_mm, abs=2e-6, rel=0)
    assert b.damper.compression_from_static_mm == pytest.approx(a.damper.compression_from_static_mm, abs=2e-6, rel=0)
    assert b.damper.motion_ratio == pytest.approx(a.damper.motion_ratio, abs=2e-8, rel=0)
    assert b.damper.stroke.status == a.damper.stroke.status
    assert b.damper.stroke.compression_clearance_mm == pytest.approx(a.damper.stroke.compression_clearance_mm, abs=2e-6, rel=0)
    assert b.damper.stroke.extension_clearance_mm == pytest.approx(a.damper.stroke.extension_clearance_mm, abs=2e-6, rel=0)


@pytest.mark.parametrize("case", [0, 1, 2])
@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("travel", [-20.0, 0.0, 20.0])
@pytest.mark.parametrize("camber,toe", [(0.0, 0.0), (-1.5, 0.8)])
def test_horizontal_translation_preserves_ground_projection_metrics(
    case: int, side: str, travel: float, camber: float, toe: float,
) -> None:
    axle = make_geometry(case)
    translated, _ = transform_axle(axle, 0, (150, -85, 0))
    first, second = DoubleWishbone(axle, side), DoubleWishbone(translated, side)
    a, b = first.solve(travel, max_step_mm=1), second.solve(travel, max_step_mm=1)
    m1 = corner_metrics(first, a, static_camber_deg=camber, static_toe_deg=toe)
    m2 = corner_metrics(second, b, static_camber_deg=camber, static_toe_deg=toe)
    for name in m1.__dataclass_fields__:
        assert getattr(m2, name) == pytest.approx(getattr(m1, name), abs=2e-6, rel=0), name
    d1 = corner_derivatives(first, a, static_camber_deg=camber, static_toe_deg=toe)
    d2 = corner_derivatives(second, b, static_camber_deg=camber, static_toe_deg=toe)
    for name in d1.__dataclass_fields__:
        assert getattr(d2, name) == pytest.approx(getattr(d1, name), abs=2e-6, rel=0), name


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("travel,expected", [(-30.0, "above_extended"), (0.0, "inside"), (30.0, "below_compressed")])
def test_frame_change_keeps_damper_conflict_classification(side: str, travel: float, expected: str) -> None:
    from suspensionlab.core.damper import LowerArmDamper

    axle = make_geometry(0)
    transformed, _ = transform_axle(axle, 35, (125, -85, 160))
    first, second = DoubleWishbone(axle, side), DoubleWishbone(transformed, side)
    limits = StrokeLimits(390, 400)
    a = LowerArmDamper(first, axle).evaluate(first.solve(travel, max_step_mm=1), limits)
    b = LowerArmDamper(second, transformed).evaluate(second.solve(travel, max_step_mm=1), limits)
    assert a.stroke is not None and b.stroke is not None
    assert a.stroke.status == b.stroke.status == expected
    assert a.has_detected_conflict == b.has_detected_conflict == (expected != "inside")
    assert b.stroke.compression_clearance_mm == pytest.approx(a.stroke.compression_clearance_mm, abs=2e-6, rel=0)
    assert b.stroke.extension_clearance_mm == pytest.approx(a.stroke.extension_clearance_mm, abs=2e-6, rel=0)
