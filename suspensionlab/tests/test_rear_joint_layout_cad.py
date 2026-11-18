"""Проверка размещения и ориентации условных втулок в CAD."""
import pytest

pytest.importorskip('OCP', exc_type=ImportError)

from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_ShapeEnum  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_assembly, build_rear_joint_layout_preview  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.entities import Project  # noqa: E402
from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept  # noqa: E402
from suspensionlab.model.rear_joint_layout import make_rear_joint_layout  # noqa: E402
from suspensionlab.model.rear_pair_snapshot import make_rear_pair_snapshot, rear_pair_sides  # noqa: E402
from suspensionlab.model.rear_tube import make_rear_tube, rear_tube_points  # noqa: E402


@pytest.mark.parametrize('axis,index', [('x', 0), ('y', 1), ('z', 2)])
def test_ten_solids_and_selected_pin_axes(axis, index):
    p = Project.create_default()
    p.rear.type_code, p.rear.layout = 'live_axle_coil', '4link_panhard'
    p.rear.ensure_points(overwrite=True)
    for code, xyz in {'ll_in_l': (0, 10, 0), 'll_out_l': (100, 110, 0),
                      'll_in_r': (0, -10, 0), 'll_out_r': (100, -110, 0)}.items():
        point = p.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    pair = make_rear_pair_snapshot(make_rear_tube(p, 'rear_lower_left', 10, 2), 'mirror')
    doc = make_rear_joint_layout(pair, make_joint_concept('bushing', DEFAULTS['bushing']), axis)
    shape = build_rear_joint_layout_preview(doc)
    assert BRepCheck_Analyzer(shape).IsValid()
    with pytest.raises(ValueError):
        build_assembly(doc)
    explorer, solids = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID), []
    while explorer.More():
        solids.append(explorer.Current())
        explorer.Next()
    assert len(solids) == 10
    points = [p for tube in rear_pair_sides(pair) for p in rear_tube_points(tube)]
    for i, point in enumerate(points):
        pin = solids[2 + i * 2 + 1]
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(pin, props)
        center = props.CentreOfMass()
        assert (center.X(), center.Y(), center.Z()) == pytest.approx(point, abs=1e-5)
        box = Bnd_Box()
        BRepBndLib.Add_s(pin, box)
        low, high = box.CornerMin(), box.CornerMax()
        spans = (high.X()-low.X(), high.Y()-low.Y(), high.Z()-low.Z())
        assert spans[index] == pytest.approx(DEFAULTS['bushing']['pin_length_mm'], abs=1e-4)
        assert all(spans[i] == pytest.approx(2*DEFAULTS['bushing']['pin_radius_mm'], abs=1e-4)
                   for i in range(3) if i != index)
    mesh = WeldmentCadJob().run(doc)
    assert len(mesh.triangles) and mesh.skipped_faces == mesh.recovered_faces == 0
