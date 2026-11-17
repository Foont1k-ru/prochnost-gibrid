"""Независимая проверка CAD-компоновки без утверждения монтажной пригодности."""
import pytest

pytest.importorskip('OCP', exc_type=ImportError)

from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_ShapeEnum  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_front_joint_layout_preview  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.entities import Project  # noqa: E402
from suspensionlab.model.front_joint_layout import make_front_joint_layout  # noqa: E402
from suspensionlab.model.front_pair_snapshot import front_pair_sides, make_front_pair_snapshot  # noqa: E402
from suspensionlab.model.front_tube_arm import front_tube_arm_points, make_front_tube_arm  # noqa: E402
from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept  # noqa: E402


def test_layout_contains_four_tubes_six_housings_and_six_pins():
    p = Project.create_default()
    pair = make_front_pair_snapshot(make_front_tube_arm(p, 'front_upper_left', 10, 2))
    doc = make_front_joint_layout(pair, make_joint_concept('ball', DEFAULTS['ball']),
                                  make_joint_concept('bushing', DEFAULTS['bushing']))
    shape = build_front_joint_layout_preview(doc)
    assert BRepCheck_Analyzer(shape).IsValid()
    explorer, solids = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID), []
    while explorer.More():
        solids.append(explorer.Current())
        explorer.Next()
    assert len(solids) == 16
    for arm_index, arm in enumerate(front_pair_sides(pair)):
        for point_index, point in enumerate(front_tube_arm_points(arm)[:2]):
            # Both symmetric bushing solids are centred at their corresponding pivot.
            for solid in solids[4 + arm_index * 6 + point_index * 2:6 + arm_index * 6 + point_index * 2]:
                props = GProp_GProps()
                BRepGProp.VolumeProperties_s(solid, props)
                center = props.CentreOfMass()
                assert (center.X(), center.Y(), center.Z()) == pytest.approx(point, abs=1e-5)
    mesh = WeldmentCadJob().run(doc)
    assert len(mesh.triangles) and mesh.skipped_faces == mesh.recovered_faces == 0


def test_same_pair_layout_joint_centers_are_independent_conditional_placements():
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    from suspensionlab.model.front_same_pair import front_same_pair_sides, make_front_same_pair

    p = Project.create_default()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (0, -100, 0), 'ubj': (100, 100, 0)}.items():
        point = p.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    arm = make_front_tube_arm(p, 'front_upper_left', 10, 2,
                              {'front': {'vertex_mm': [100, 0, 30], 'radius_mm': 20}})
    pair = make_front_same_pair(arm)
    doc = make_front_joint_layout(pair, make_joint_concept('ball', DEFAULTS['ball']),
                                  make_joint_concept('bushing', DEFAULTS['bushing']))
    shape = build_front_joint_layout_preview(doc)
    assert BRepCheck_Analyzer(shape).IsValid()
    explorer, solids = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID), []
    while explorer.More():
        solids.append(explorer.Current())
        explorer.Next()
    assert len(solids) == 16
    for arm_index, arm in enumerate(front_same_pair_sides(pair)):
        points = front_tube_arm_points(arm)
        for index, point in enumerate(points[:2]):
            for solid in solids[4 + arm_index * 6 + index * 2:6 + arm_index * 6 + index * 2]:
                props = GProp_GProps()
                BRepGProp.VolumeProperties_s(solid, props)
                center = props.CentreOfMass()
                assert (center.X(), center.Y(), center.Z()) == pytest.approx(point, abs=1e-5)
        # Ball pin points +Z on both sides, regardless of tube rotation.
        box = Bnd_Box()
        BRepBndLib.Add_s(solids[4 + arm_index * 6 + 5], box)
        assert box.CornerMax().Z() == pytest.approx(points[2][2] + DEFAULTS['ball']['pin_length_mm'], abs=1e-4)
    mesh = WeldmentCadJob().run(doc)
    assert len(mesh.triangles) and mesh.skipped_faces == mesh.recovered_faces == 0
