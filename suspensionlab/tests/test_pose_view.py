"""Координаты для схемы должны совпадать с рассчитанной пространственной геометрией."""
from math import dist

import numpy as np
import pytest

from suspensionlab.core.damper import LowerArmDamper
from suspensionlab.core.double_wishbone import DoubleWishbone
from suspensionlab.core.pose_view import pose_view
from suspensionlab.core.springs import lower_arm_spring_length
from suspensionlab.model.templates import load_template


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("travel", [-20, 0, 20])
def test_preview_uses_solved_points_and_mounts(side, travel):
    axle = load_template("ring").front
    before = axle.to_dict()
    model = DoubleWishbone(axle, side)
    pose = model.solve(travel)
    frame = pose_view(model, pose, axle, spring=True, damper=True)
    assert frame.center == pytest.approx(pose.center)
    assert frame.upper_ball == pytest.approx(pose.point(model.points["ubj"], model.center0))
    assert frame.lower_ball == pytest.approx(pose.point(model.points["lbj"], model.center0))
    assert frame.upper_front == pytest.approx(model.points["uca_f_in"])
    assert frame.spring is not None and frame.damper is not None
    low, high = axle.hardpoints["spring_lo"], axle.hardpoints["spring_up"]
    lower = np.array((low.x, low.y * model.sign, low.z))
    upper = np.array((high.x, high.y * model.sign, high.z))
    assert dist(*frame.spring) == pytest.approx(lower_arm_spring_length(model, pose, lower, upper))
    assert dist(*frame.damper) == pytest.approx(LowerArmDamper(model, axle).evaluate(pose).length_mm)
    assert axle.to_dict() == before


def test_preview_is_mirrored_and_components_require_explicit_assumption():
    axle = load_template("ring").front
    left, right = DoubleWishbone(axle, "left"), DoubleWishbone(axle, "right")
    left_frame = pose_view(left, left.solve(20), axle, spring=True, damper=True)
    right_frame = pose_view(right, right.solve(20), axle, spring=True, damper=True)
    for a, b in ((left_frame.center, right_frame.center), (left_frame.lower_ball, right_frame.lower_ball),
                 (left_frame.spring[0], right_frame.spring[0]), (left_frame.damper[1], right_frame.damper[1])):
        assert b == pytest.approx((a[0], -a[1], a[2]), abs=1e-7)
    plain = pose_view(left, left.solve(20), axle, spring=False, damper=False)
    assert plain.spring is None and plain.damper is None


def test_preview_rejects_nonfinite_mount():
    axle = load_template("ring").front
    model = DoubleWishbone(axle)
    axle.hardpoints["spring_lo"].x = float("nan")
    with pytest.raises(ValueError):
        pose_view(model, model.initial_pose(), axle, spring=True, damper=False)
