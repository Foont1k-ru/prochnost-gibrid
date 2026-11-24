"""Проверка отдельных тел и изолированного CAD-работника свободного черновика."""
from math import dist, pi

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)

from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_SOLID  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402

from suspensionlab.core.cad_free_arm import build_free_arm_tubes  # noqa: E402
from suspensionlab.core.cad_transport import CadPreviewError  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.bent_tube import make_bend_path  # noqa: E402
from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft  # noqa: E402
from suspensionlab.model.free_arm_io import FreeArmFileError, to_data  # noqa: E402


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


@pytest.mark.parametrize('bent_front,bent_rear', [(False, False), (True, False), (False, True), (True, True)])
def test_real_solids_centerlines_and_isolated_mesh(bent_front, bent_rear):
    front, rear, outer = (0, 0, 0), (0, 200, 0), (300, 100, 10)
    front_bend = FreeArmBend((150, 20, 50), 20) if bent_front else None
    rear_bend = FreeArmBend((150, 180, 50), 20) if bent_rear else None
    draft = FreeArmDraft(front, rear, outer, 10, 2, front_bend, rear_bend)
    compound, parts = build_free_arm_tubes(draft)
    assert BRepCheck_Analyzer(compound).IsValid()
    solids = TopExp_Explorer(compound, TopAbs_SOLID)
    count = 0
    while solids.More():
        count += 1
        solids.Next()
    assert count == 2
    for start, bend, shape, line in zip((front, rear), (front_bend, rear_bend), parts, draft.centerlines(), strict=True):
        length = (dist(start, outer) if bend is None else
                  make_bend_path(start, bend.vertex_mm, outer, bend.radius_mm, draft.radius_mm).length)
        assert line[0] == start and line[-1] == outer
        assert BRepCheck_Analyzer(shape).IsValid()
        assert volume(shape) == pytest.approx(pi * (10**2 - 8**2) * length, rel=1e-7)
    mesh = WeldmentCadJob().run(to_data(draft), deviation=2)
    assert mesh.part_names == ('tube_front', 'tube_rear')
    assert mesh.triangle_parts is not None and set(mesh.triangle_parts.tolist()) == {0, 1}
    assert mesh.skipped_faces == mesh.recovered_faces == 0


def test_invalid_and_cancelled_job_never_builds():
    draft = FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2)
    data = to_data(draft)
    data['anchors_mm']['outer'] = data['anchors_mm']['front']
    with pytest.raises(FreeArmFileError):
        WeldmentCadJob().run(data)
    job = WeldmentCadJob()
    job.cancel()
    with pytest.raises(CadPreviewError, match='cancelled'):
        job.run(to_data(draft))
