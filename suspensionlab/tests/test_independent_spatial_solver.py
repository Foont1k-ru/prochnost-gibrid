"""Численная перекрёстная проверка 3D-связей; не внешний CAD-эталон.

Опорный алгоритм использует собственные уравнения расстояний, абсолютный
вектор поворота и scipy least_squares с численным якобианом. Он не вызывает
систему уравнений, шаг Ньютона, якобиан или мгновенные скорости ядра.
Обе реализации всё же основаны на одинаковых идеальных связях и SciPy.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, sin

import numpy as np
import pytest
from scipy.optimize import least_squares

from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.equilibrium import SpringEquilibrium
from suspensionlab.model.entities import Axle
from suspensionlab.model.templates import load_template

# Учебные координаты в мм: не являются измерениями реального автомобиля.
POINTS = {
    "uca_f_in": (90, 330, 395), "uca_r_in": (-110, 340, 400), "ubj": (-5, 655, 430),
    "lca_f_in": (120, 250, 140), "lca_r_in": (-140, 260, 150), "lbj": (0, 690, 145),
    "tierod_in": (-120, 280, 170), "tierod_out": (-150, 640, 175), "wheel_center": (0, 762, 310),
    "spring_lo": (0, 520, 150), "spring_up": (0, 430, 560),
}
PAIRS = (("ubj", "uca_f_in"), ("ubj", "uca_r_in"), ("lbj", "lca_f_in"),
         ("lbj", "lca_r_in"), ("tierod_out", "tierod_in"))


def create_axle(case: int) -> Axle:
    axle = load_template("ring").front
    offsets = {
        0: {},
        1: {"uca_f_in": (6, -5, 4), "uca_r_in": (-4, 3, -7), "ubj": (5, -6, 3),
            "lca_f_in": (-5, 6, -4), "lbj": (4, 5, -3), "tierod_out": (8, -4, 5),
            "spring_lo": (7, -4, 5)},
        2: {"uca_r_in": (7, -8, 5), "ubj": (-8, 6, -4), "lca_r_in": (4, 7, 6),
            "lbj": (-6, -5, 4), "tierod_in": (-7, 5, 3), "tierod_out": (3, 4, -5),
            "spring_up": (5, -6, 3)},
    }
    for name, original in POINTS.items():
        delta = offsets[case].get(name, (0, 0, 0))
        p = axle.hardpoints[name]
        p.x, p.y, p.z = (float(a + b) for a, b in zip(original, delta, strict=True))
    return axle


def rotation_matrix(rotvec: np.ndarray) -> np.ndarray:
    """Формула Родрига для абсолютного вектора поворота без scipy Rotation."""
    x, y, z = rotvec
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    theta = float(np.linalg.norm(rotvec))
    if theta < 1e-6:
        a = 1 - theta**2 / 6 + theta**4 / 120
        b = 0.5 - theta**2 / 24 + theta**4 / 720
    else:
        a = sin(theta) / theta
        b = (1 - cos(theta)) / theta**2
    return np.eye(3) + a * cross + b * (cross @ cross)


@dataclass(frozen=True)
class ReferencePose:
    center: np.ndarray
    rotation: np.ndarray
    variables: np.ndarray


class ReferenceSolver:
    """Независимое численное продолжение с расстояниями в мм."""

    def __init__(self, axle: Axle, side: str) -> None:
        sign = 1 if side == "left" else -1
        self.points = {name: np.array([axle.hardpoints[name].x, sign * axle.hardpoints[name].y,
                                       axle.hardpoints[name].z], dtype=float) for name in POINTS}
        self.center = self.points["wheel_center"]
        self.lengths = [float(np.linalg.norm(self.points[m] - self.points[f])) for m, f in PAIRS]

    def residual(self, variables: np.ndarray, travel: float) -> np.ndarray:
        center, rotation = variables[:3], rotation_matrix(variables[3:])
        residual = [np.linalg.norm(center + rotation @ (self.points[m] - self.center) - self.points[f]) - length
                    for (m, f), length in zip(PAIRS, self.lengths, strict=True)]
        residual.append(center[2] - self.center[2] - travel)
        return np.array(residual)

    def refine(self, travel: float, initial: np.ndarray) -> ReferencePose:
        fit = least_squares(self.residual, initial, args=(travel,), jac="3-point", method="trf",
                            x_scale=np.array([100, 100, 100, 1, 1, 1]),
                            ftol=1e-13, xtol=1e-13, gtol=1e-13, max_nfev=300)
        assert fit.success, fit.message
        assert np.max(np.abs(self.residual(fit.x, travel))) < 1e-8
        return ReferencePose(fit.x[:3].copy(), rotation_matrix(fit.x[3:]), fit.x.copy())

    def solve(self, travel: float) -> ReferencePose:
        variables = np.concatenate((self.center, np.zeros(3)))
        count = max(1, int(np.ceil(abs(travel) / 2)))
        pose = self.refine(0, variables)
        for step in np.linspace(0, travel, count + 1)[1:]:
            pose = self.refine(float(step), pose.variables)
        return pose

    def point(self, pose: ReferencePose, name: str) -> np.ndarray:
        return pose.center + pose.rotation @ (self.points[name] - self.center)

    def spring_distance(self, pose: ReferencePose) -> float:
        origin = self.points["lca_f_in"]
        axis = self.points["lca_r_in"] - origin
        axis /= np.linalg.norm(axis)
        initial = self.points["lbj"] - origin
        current = self.point(pose, "lbj") - origin
        initial -= axis * np.dot(initial, axis)
        current -= axis * np.dot(current, axis)
        angle = atan2(float(np.dot(axis, np.cross(initial, current))), float(np.dot(initial, current)))
        mount = origin + rotation_matrix(axis * angle) @ (self.points["spring_lo"] - origin)
        return float(np.linalg.norm(self.points["spring_up"] - mount))


@pytest.mark.parametrize("case", [0, 1, 2])
@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("travel", [-25.0, 0.0, 25.0])
def test_spatial_motion_against_independent_solver(case: int, side: str, travel: float) -> None:
    axle = create_axle(case)
    reference = ReferenceSolver(axle, side)
    expected = reference.solve(travel)
    model = DoubleWishbone(axle, side)
    actual = model.solve(travel, max_step_mm=1)
    np.testing.assert_allclose(actual.center, expected.center, rtol=0, atol=2e-6)
    np.testing.assert_allclose(actual.rotation, expected.rotation, rtol=0, atol=2e-8)
    for point in ("ubj", "lbj", "tierod_out"):
        np.testing.assert_allclose(actual.point(model.points[point], model.center0), reference.point(expected, point),
                                   rtol=0, atol=2e-6)
    if travel:
        assert np.linalg.norm(expected.rotation - np.eye(3)) > 1e-3
        assert np.count_nonzero(np.abs(expected.variables[3:]) > 1e-4) >= 2


@pytest.mark.parametrize("case", [0, 1, 2])
@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("travel", [-20.0, 0.0, 20.0])
def test_spring_length_and_motion_ratio_against_independent_solver(case: int, side: str, travel: float) -> None:
    axle = create_axle(case)
    reference = ReferenceSolver(axle, side)
    current = reference.solve(travel)
    static = reference.solve(0)
    expected_length = 230 + reference.spring_distance(current) - reference.spring_distance(static)
    step = 0.01
    low = reference.refine(travel - step, current.variables)
    high = reference.refine(travel + step, current.variables)
    expected_ratio = (reference.spring_distance(low) - reference.spring_distance(high)) / (2 * step)
    sample = SpringEquilibrium(axle, 230, side=side, coil_bind_length_mm=150).evaluate(travel, 1)
    assert sample.spring.length_mm == pytest.approx(expected_length, abs=2e-6, rel=0)
    assert sample.motion_ratio == pytest.approx(expected_ratio, abs=2e-6, rel=0)


def test_reference_constraints_detect_a_disturbed_pose() -> None:
    reference = ReferenceSolver(create_axle(1), "left")
    pose = reference.solve(20)
    disturbed = pose.variables.copy()
    disturbed[0] += 1
    assert np.max(np.abs(reference.residual(disturbed, 20))) > 0.01


def test_reference_rodrigues_identity_and_quarter_turn() -> None:
    from math import pi

    zero = rotation_matrix(np.zeros(3))
    np.testing.assert_allclose(zero, np.eye(3), atol=1e-15, rtol=0)
    turn = rotation_matrix(np.array([0.0, 0.0, pi / 2]))
    np.testing.assert_allclose(turn @ np.array([1.0, 0.0, 0.0]), [0.0, 1.0, 0.0], atol=1e-14, rtol=0)
    np.testing.assert_allclose(turn.T @ turn, np.eye(3), atol=1e-14, rtol=0)
    assert np.linalg.det(turn) == pytest.approx(1.0, abs=1e-14, rel=0)
