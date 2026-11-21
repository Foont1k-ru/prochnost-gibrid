"""Сопоставление дерева с реальными CAD-треугольниками для трубных видов."""
import numpy as np
import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402
from OCP.TopoDS import TopoDS_Iterator  # noqa: E402
from test_front_pair_snapshot import project as front_project  # noqa: E402

from suspensionlab.core.cad_kim_prototype import (  # noqa: E402
    build_front_arm_tubes_preview,
    build_part,
    build_rear_tube_preview,
)
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.entities import Project  # noqa: E402
from suspensionlab.model.front_pair_snapshot import front_pair_sides, make_front_pair_snapshot  # noqa: E402
from suspensionlab.model.front_same_pair import front_same_pair_sides, make_front_same_pair  # noqa: E402
from suspensionlab.model.front_tube_arm import make_front_tube_arm  # noqa: E402
from suspensionlab.model.rear_pair_snapshot import make_rear_pair_snapshot, rear_pair_sides  # noqa: E402
from suspensionlab.model.rear_tube import make_rear_tube  # noqa: E402
from suspensionlab.model.welded_arm import make_welded_arm  # noqa: E402


def children(shape):
    iterator, result = TopoDS_Iterator(shape), []
    while iterator.More():
        result.append(iterator.Value())
        iterator.Next()
    return result


def verify(doc, identifiers, shapes):
    mesh = WeldmentCadJob().run(doc, deviation=.2)
    assert mesh.part_names == identifiers and mesh.triangle_parts is not None
    assert set(mesh.triangle_parts) == set(range(len(shapes)))
    for index, shape in enumerate(shapes):
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, box, False, False)
        low, high = box.CornerMin(), box.CornerMax()
        expected = np.array([[low.X(), low.Y(), low.Z()], [high.X(), high.Y(), high.Z()]])
        points = mesh.triangles[mesh.triangle_parts == index]
        actual = np.array([points.min(axis=(0, 1)), points.max(axis=(0, 1))])
        assert np.allclose(actual, expected, atol=.6, rtol=0)


def test_two_original_weldment_tubes_have_individual_groups():
    p = front_project()
    doc = make_welded_arm(p, 10, 2, 'unknown')
    verify(doc, ('tube_front', 'tube_rear'), [build_part(part) for part in doc['parts']])


def test_front_arm_and_mirror_pair_have_four_distinct_groups():
    arm = make_front_tube_arm(front_project(), 'front_upper_right', 10, 2)
    verify(arm, ('tube_front', 'tube_rear'), children(build_front_arm_tubes_preview(arm)))
    pair = make_front_pair_snapshot(arm)
    shapes = [shape for side in front_pair_sides(pair) for shape in children(build_front_arm_tubes_preview(side))]
    verify(pair, ('source_tube_front', 'source_tube_rear', 'paired_tube_front', 'paired_tube_rear'), shapes)


def test_same_part_pair_keeps_source_and_transformed_groups_distinct():
    arm = make_front_tube_arm(front_project(), 'front_upper_left', 10, 2,
                              {'front': {'vertex_mm': [100, 0, 30], 'radius_mm': 20}})
    pair = make_front_same_pair(arm)
    shapes = [shape for side in front_same_pair_sides(pair) for shape in children(build_front_arm_tubes_preview(side))]
    verify(pair, ('source_tube_front', 'source_tube_rear', 'paired_tube_front', 'paired_tube_rear'), shapes)


@pytest.mark.parametrize(('mode', 'roll'), [('mirror', 0), ('same', 35)])
def test_rear_single_and_pair_show_real_tubes(mode, roll):
    p = Project.create_default()
    p.rear.type_code, p.rear.layout = 'live_axle_coil', '4link_panhard'
    p.rear.ensure_points(overwrite=True)
    for code, xyz in {'ll_in_l': (0, 10, 0), 'll_out_l': (100, 110, 0),
                      'll_in_r': (0, -10, 0), 'll_out_r': (100, -110, 0)}.items():
        point = p.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    tube = make_rear_tube(p, 'rear_lower_left', 10, 2, {'vertex_mm': [100, 10, 0], 'radius_mm': 20})
    verify(tube, ('tube',), [build_rear_tube_preview(tube)])
    pair = make_rear_pair_snapshot(tube, mode, roll)
    verify(pair, ('source_tube', 'paired_tube'), [build_rear_tube_preview(t) for t in rear_pair_sides(pair)])
