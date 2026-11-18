"""BRep двух отдельных частей и отсутствие численного объёмного пересечения."""
import math

import pytest

pytest.importorskip('OCP', exc_type=ImportError)

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_ShapeEnum  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_assembly, build_joint_preview  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept  # noqa: E402


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


@pytest.mark.parametrize('kind', ['ball', 'bushing'])
def test_real_shapes_are_valid_distinct_and_worker_meshes_them(kind):
    doc = make_joint_concept(kind, DEFAULTS[kind])
    shape = build_joint_preview(doc)
    assert BRepCheck_Analyzer(shape).IsValid()
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    solids = []
    while explorer.More():
        solids.append(explorer.Current())
        explorer.Next()
    assert len(solids) == 2 and all(volume(s) > 0 for s in solids)
    common = BRepAlgoAPI_Common(solids[0], solids[1])
    assert common.IsDone() and abs(volume(common.Shape())) < 1e-7
    if kind == 'bushing':
        p = doc['parameters']
        expected = (math.pi * (p['outer_radius_mm']**2-p['bore_radius_mm']**2) * p['body_length_mm'] +
                    math.pi * p['pin_radius_mm']**2 * p['pin_length_mm'])
        assert volume(shape) == pytest.approx(expected, rel=1e-7)
    with pytest.raises(ValueError):
        build_assembly(doc)
    mesh = WeldmentCadJob().run(doc)
    assert len(mesh.triangles) > 0 and mesh.skipped_faces == mesh.recovered_faces == 0
