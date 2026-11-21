"""Проверка четырёх раздельных тел и произвольных осей реальным CAD-ядром."""
from math import hypot, pi

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopoDS import TopoDS_Iterator  # noqa: E402
from test_fixed_arm_housings import housings  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_fixed_arm_housing_preview, build_part  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.fixed_arm_housings import make_housing_preview  # noqa: E402
from suspensionlab.model.fixed_arm_skeleton import (  # noqa: E402
    capture_fixed_arm,
    fixed_arm_tube_document,
    preview_fixed_arm,
)
from suspensionlab.model.templates import load_template  # noqa: E402


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


@pytest.mark.parametrize('bent', [False, True])
def test_housings_placement_and_worker_without_notching(bent):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    vertex = [(anchors[0][i] + anchors[2][i]) / 2 for i in range(3)]
    vertex[2] += 50
    bends = {'front': {'vertex_mm': vertex, 'radius_mm': 20}} if bent else {}
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2, bends)
    settings = housings()
    doc = make_housing_preview(tubes, settings)
    shape = build_fixed_arm_housing_preview(doc)
    it = TopoDS_Iterator(shape)
    parts = []
    while it.More():
        parts.append(it.Value())
        it.Next()
    assert len(parts) == 4
    assert all(BRepCheck_Analyzer(part).IsValid() for part in parts)
    # Tube volumes remain identical to the uncut independent tube solids.
    for i in range(2):
        assert volume(parts[i]) == pytest.approx(volume(build_part(tubes['parts'][i])), rel=1e-8)
    for i, leg in enumerate(('front', 'rear')):
        spec = settings[leg]
        assert volume(parts[i + 2]) == pytest.approx(pi / 4 * (spec['outer_diameter_mm']**2 -
                                                     spec['bore_diameter_mm']**2) * spec['length_mm'], rel=1e-8)
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(parts[i + 2], box)
        bounds = (box.GetXMin(), box.GetYMin(), box.GetZMin(), box.GetXMax(), box.GetYMax(), box.GetZMax())
        direction = [v / hypot(*spec['axis']) for v in spec['axis']]
        for j in range(3):
            assert (bounds[j] + bounds[j + 3]) / 2 == pytest.approx(anchors[i][j], abs=1e-5)
            extent = abs(direction[j]) * spec['length_mm'] + spec['outer_diameter_mm'] * (1 - direction[j]**2)**0.5
            assert bounds[j + 3] - bounds[j] == pytest.approx(extent, abs=1e-5)
    mesh = WeldmentCadJob().run(doc, deviation=2)
    assert mesh.part_names == ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    assert mesh.triangle_parts is not None and set(mesh.triangle_parts.tolist()) == {0, 1, 2, 3}
    assert mesh.skipped_faces == mesh.recovered_faces == 0
