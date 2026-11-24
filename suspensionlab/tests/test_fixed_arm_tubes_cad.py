"""Реальная CAD-геометрия труб по зафиксированным опорам; не расчёт прочности."""
from math import dist, pi

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)

from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_SOLID  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_part, build_weldment_tubes_preview  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.bent_tube import make_bend_path  # noqa: E402
from suspensionlab.model.fixed_arm_skeleton import (  # noqa: E402
    SkeletonError,
    capture_fixed_arm,
    fixed_arm_tube_document,
    preview_fixed_arm,
)
from suspensionlab.model.templates import load_template  # noqa: E402


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


@pytest.mark.parametrize('legs', [(), ('front',), ('rear',), ('front', 'rear')])
def test_frozen_tubes_actual_solids_centerlines_and_grouped_worker(legs):
    project = load_template('ring')
    before = project.to_dict()
    snapshot = capture_fixed_arm(project, -20, 20)
    straight = preview_fixed_arm(snapshot, project, 10, 2)
    b = straight.anchors[2]
    bends = {}
    for index, leg in enumerate(('front', 'rear')):
        a = straight.anchors[index]
        vertex = [(a[0] + b[0]) / 2 + 70, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2 + 70]
        if leg in legs:
            bends[leg] = {'vertex_mm': vertex, 'radius_mm': 20}
    doc = fixed_arm_tube_document(snapshot, project, 10, 2, bends)
    view = preview_fixed_arm(snapshot, project, 10, 2, bends)
    assert doc['version'] == ('0.3' if legs else '0.2') and doc['damper_mount'] == 'unknown'
    assert len(doc['parts']) == 2 and doc['parts'][0]['geometry']['source']['coordinates_mm'] == [list(p) for p in view.anchors]
    section = pi * (10**2 - 8**2)
    for index, leg in enumerate(('front', 'rear')):
        a = view.anchors[index]
        assert view.centerlines[index][0] == a and view.centerlines[index][-1] == b
        solid = build_part(doc['parts'][index])
        assert BRepCheck_Analyzer(solid).IsValid()
        length = (make_bend_path(a, bends[leg]['vertex_mm'], b, 20, 10).length
                  if leg in bends else dist(a, b))
        assert volume(solid) == pytest.approx(section * length, rel=1e-7)
    combined = build_weldment_tubes_preview(doc)
    explorer = TopExp_Explorer(combined, TopAbs_SOLID)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    assert count == 2
    mesh = WeldmentCadJob().run(doc, deviation=2)
    assert mesh.part_names == ('tube_front', 'tube_rear')
    assert mesh.triangle_parts is not None and set(mesh.triangle_parts.tolist()) == {0, 1}
    assert mesh.skipped_faces == mesh.recovered_faces == 0
    assert project.to_dict() == before
    project.front.hardpoints['lbj'].x += 1
    with pytest.raises(SkeletonError, match='изменился'):
        fixed_arm_tube_document(snapshot, project, 10, 2, bends)
