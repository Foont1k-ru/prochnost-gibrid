"""CAD preview for the same-part front pair."""
import pytest

pytest.importorskip('OCP', exc_type=ImportError)

from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.TopAbs import TopAbs_ShapeEnum  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from test_front_pair_snapshot import project  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_front_pair_preview  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.front_same_pair import make_front_same_pair  # noqa: E402
from suspensionlab.model.front_tube_arm import make_front_tube_arm  # noqa: E402


def test_same_front_pair_creates_four_valid_solids_and_worker_mesh():
    arm = make_front_tube_arm(project(), 'front_upper_left', 10, 2,
                             {'front': {'vertex_mm': [100, 0, 30], 'radius_mm': 20}})
    pair = make_front_same_pair(arm)
    shape = build_front_pair_preview(pair)
    assert BRepCheck_Analyzer(shape).IsValid()
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    assert count == 4
    mesh = WeldmentCadJob().run(pair)
    assert len(mesh.triangles) and not mesh.skipped_faces and not mesh.recovered_faces
