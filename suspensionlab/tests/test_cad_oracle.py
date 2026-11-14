"""Независимая сверка активного перемещения с Open CASCADE (только в CAD CI).

Этот тест не проверяет семантику ITEM_DEFINED_TRANSFORMATION и не импортирует STEP.
"""
from math import cos, pi, sin

import pytest

pytest.importorskip("OCP", reason="Опциональный CAD-эталон устанавливается отдельно", exc_type=ImportError)
from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf  # noqa: E402

from suspensionlab.core.spatial_transform import RigidTransform, SpatialFrame  # noqa: E402


def cad_frame(frame):
    return gp_Ax3(gp_Pnt(*frame.origin), gp_Dir(*frame.z), gp_Dir(*frame.x))


def cad_move(source, target):
    transform = gp_Trsf()
    transform.SetDisplacement(cad_frame(source), cad_frame(target))
    return transform


def point_cad(transform, point):
    p = gp_Pnt(*point).Transformed(transform)
    return p.X(), p.Y(), p.Z()


def xyz(z_angle, origin):
    c, s = cos(z_angle), sin(z_angle)
    return SpatialFrame(origin, (c, s, 0), (-s, c, 0), (0, 0, 1))


def test_active_frame_alignment_matches_opencascade():
    source = xyz(0.6, (12, -4, 3))
    target = SpatialFrame((-2, 7, 8), (0, 0, 1), (0, 1, 0), (-1, 0, 0))
    reference = cad_move(source, target)
    actual = RigidTransform.align_frames_same_units(source, target)
    for point in ((0, 0, 0), source.origin, (1, 2, 3), (-1.25, 60, -8), (1e4, -5e3, 2e3)):
        assert actual.apply_point(point) == pytest.approx(point_cad(reference, point), abs=1e-8)
        moved = actual.apply_point(point)
        assert actual.inverse().apply_point(moved) == pytest.approx(point, abs=1e-8)


def test_noncommuting_nested_displacements_match_opencascade():
    base = xyz(0, (0, 0, 0))
    parent_frame = xyz(pi / 2, (10, 0, 0))
    child_frame = xyz(pi / 4, (2, 0, 5))
    parent = RigidTransform.align_frames_same_units(base, parent_frame)
    child = RigidTransform.align_frames_same_units(base, child_frame)
    reference = cad_move(base, parent_frame).Multiplied(cad_move(base, child_frame))
    for point in ((0, 0, 0), (1, 2, 3), (-3, 8, -2)):
        assert parent.compose(child).apply_point(point) == pytest.approx(point_cad(reference, point), abs=1e-8)
    assert parent.compose(child).apply_point((0, 0, 0)) != pytest.approx(child.compose(parent).apply_point((0, 0, 0)))
