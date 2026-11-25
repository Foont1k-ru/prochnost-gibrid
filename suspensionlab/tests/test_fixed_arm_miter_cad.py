"""Геометрические инварианты пробного общего стыка, не проверка изготовления."""
from copy import deepcopy
from math import dist, pi

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRepAdaptor import BRepAdaptor_Surface  # noqa: E402
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GeomAbs import GeomAbs_Plane  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_FACE  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from OCP.TopoDS import TopoDS, TopoDS_Iterator  # noqa: E402

from suspensionlab.core.cad_fixed_arm_miter import MiterError, build_miter_tubes, miter_geometry  # noqa: E402
from suspensionlab.core.cad_kim_prototype import (  # noqa: E402
    build_fixed_arm_housing_preview,
    build_weldment_tubes_preview,
)
from suspensionlab.core.cad_transport import CadPreviewError  # noqa: E402
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
    BRepGProp.VolumeProperties_s(shape, props, 1e-8)
    return float(props.Mass())


def original_parts(shape):
    iterator = TopoDS_Iterator(shape)
    result = []
    while iterator.More():
        result.append(iterator.Value())
        iterator.Next()
    return result


def cut_face_areas(shape, geometry):
    iterator = TopExp_Explorer(shape, TopAbs_FACE)
    areas = []
    while iterator.More():
        face = TopoDS.Face(iterator.Current())
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Plane:
            plane = surface.Plane()
            location = plane.Location()
            normal = plane.Axis().Direction()
            p = (location.X(), location.Y(), location.Z())
            n = (normal.X(), normal.Y(), normal.Z())
            displacement = sum((p[i] - geometry.point[i]) * geometry.normal[i] for i in range(3))
            alignment = abs(sum(n[i] * geometry.normal[i] for i in range(3)))
            if abs(displacement) < 1e-6 and alignment > 1 - 1e-8:
                props = GProp_GProps()
                BRepGProp.SurfaceProperties_s(face, props, 1e-8)
                areas.append(float(props.Mass()))
        iterator.Next()
    return areas


@pytest.mark.parametrize('bent', [(), ('front',), ('rear',), ('front', 'rear')])
def test_shared_plane_produces_both_complete_mating_faces(bent):
    project = load_template('ring')
    before_project = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    bends = {}
    for index, leg in enumerate(('front', 'rear')):
        if leg in bent:
            vertex = [(anchors[index][i] + anchors[2][i]) / 2 for i in range(3)]
            vertex[2] += 50 if leg == 'front' else -40
            bends[leg] = {'vertex_mm': vertex, 'radius_mm': 20}
    document = fixed_arm_tube_document(snapshot, project, 10, 2, bends)
    before_document = deepcopy(document)
    geometry = miter_geometry(document)
    original = original_parts(build_weldment_tubes_preview(document))
    tubes = build_miter_tubes(document)
    assert len(tubes) == 2 and all(BRepCheck_Analyzer(tube).IsValid() for tube in tubes)
    sine = abs(sum(geometry.normal[i] * geometry.directions[0][i] for i in range(3)))
    expected_area = pi * (10**2 - 8**2) / sine
    for tube, prior in zip(tubes, original, strict=True):
        areas = cut_face_areas(tube, geometry)
        assert len(areas) == 1
        assert areas[0] == pytest.approx(expected_area, rel=1e-6)
        # Equal amount removed and added around the original end plane.
        assert volume(tube) == pytest.approx(volume(prior), rel=1e-6)
    common = BRepAlgoAPI_Common(*tubes)
    assert common.IsDone() and abs(volume(common.Shape())) < 1e-5
    distance = BRepExtrema_DistShapeShape(*tubes)
    assert distance.IsDone() and distance.Value() < 1e-6
    assert dist(geometry.point, anchors[2]) < 1e-9
    assert document == before_document and project.to_dict() == before_project


def test_miter_preview_worker_builds_two_mesh_parts_and_reports_invalid_geometry():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    joint = {'target': 'miter', 'radial_clearance_mm': 0.}
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2)
    doc = make_housing_preview(tubes, None, tube_joint=joint)
    shape = build_fixed_arm_housing_preview(doc)
    assert len(original_parts(shape)) == 2
    mesh = WeldmentCadJob().run(doc, deviation=2)
    assert mesh.part_names == ('tube_front', 'tube_rear')
    assert set(mesh.triangle_parts.tolist()) == {0, 1}
    bad = make_housing_preview(fixed_arm_tube_document(snapshot, project, 200, 2), None, tube_joint=joint)
    with pytest.raises(CadPreviewError) as exc:
        WeldmentCadJob().run(bad, deviation=2)
    assert exc.value.code == 'tube_joint_miter_failed'


def test_miter_that_reaches_the_opposite_support_is_rejected():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, 0, 0)
    document = fixed_arm_tube_document(snapshot, project, 200, 2)
    with pytest.raises(MiterError, match='за конечный прямой участок'):
        miter_geometry(document)


def test_too_close_directions_are_rejected():
    project = load_template('ring')
    # Both inner anchors share a nearly identical direction from the ball.
    front = project.front.hardpoints['lca_f_in']
    rear = project.front.hardpoints['lca_r_in']
    rear.x, rear.y, rear.z = front.x + .1, front.y, front.z
    snapshot = capture_fixed_arm(project, 0, 0)
    document = fixed_arm_tube_document(snapshot, project, 10, 2)
    with pytest.raises(MiterError, match='слишком близки'):
        miter_geometry(document)


def test_miter_with_housings_notches_and_overlap_checks():
    from test_fixed_arm_housings import housings

    from suspensionlab.core.cad_fixed_arm_overlap import measure_all_pairs
    from suspensionlab.core.fixed_arm_suggestions import candidate_document, candidate_options

    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2)
    doc = make_housing_preview(tubes, housings(), {'front': 0., 'rear': 0.},
                               {'target': 'miter', 'radial_clearance_mm': 0.})
    shape = build_fixed_arm_housing_preview(doc)
    parts = original_parts(shape)
    assert len(parts) == 4
    geometry = miter_geometry(tubes)
    for part in parts[:2]:
        assert len(cut_face_areas(part, geometry)) == 1
    rows = measure_all_pairs(doc)
    assert len(rows) == 6 and rows[0]['overlap_mm3'] < 1e-5
    options, constrained = candidate_options(doc, 'tube_front', 'tube_rear', 1.)
    assert not options and constrained
    with pytest.raises(ValueError, match='existing_joint'):
        candidate_document(doc, 'joint', 'front', 1.)


def test_later_cut_damaging_miter_face_is_rejected():
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Pnt

    from suspensionlab.core.cad_fixed_arm_miter import validate_miter_face

    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    doc = fixed_arm_tube_document(snapshot, project, 10, 2)
    geometry = miter_geometry(doc)
    tube = build_miter_tubes(doc)[0]
    cutter = BRepPrimAPI_MakeSphere(gp_Pnt(*geometry.point), 15).Shape()
    cut = BRepAlgoAPI_Cut(tube, cutter)
    assert cut.IsDone()
    with pytest.raises(MiterError, match='Поверхность стыка'):
        validate_miter_face(cut.Shape(), geometry, doc['parts'][0]['geometry'], 0)


@pytest.mark.parametrize('bent', [(), ('front',), ('rear',), ('front', 'rear')])
def test_miter_faces_cover_the_same_area_not_just_equal_areas(bent):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    bends = {}
    for index, leg in enumerate(('front', 'rear')):
        if leg in bent:
            vertex = [(anchors[index][i] + anchors[2][i]) / 2 for i in range(3)]
            vertex[2] += 50 if leg == 'front' else -40
            bends[leg] = {'vertex_mm': vertex, 'radius_mm': 20}
    doc = fixed_arm_tube_document(snapshot, project, 10, 2, bends)
    miter = miter_geometry(doc)
    faces = []
    for shape in build_miter_tubes(doc):
        matches = []
        it = TopExp_Explorer(shape, TopAbs_FACE)
        while it.More():
            face = TopoDS.Face(it.Current())
            surface = BRepAdaptor_Surface(face)
            if surface.GetType() == GeomAbs_Plane:
                plane = surface.Plane()
                origin, direction = plane.Location(), plane.Axis().Direction()
                point = (origin.X(), origin.Y(), origin.Z())
                normal = (direction.X(), direction.Y(), direction.Z())
                if (abs(sum((point[i] - miter.point[i]) * miter.normal[i] for i in range(3))) < 1e-6 and
                        abs(sum(normal[i] * miter.normal[i] for i in range(3))) > 1 - 1e-8):
                    matches.append(face)
            it.Next()
        assert len(matches) == 1
        faces.append(matches[0])
    common = BRepAlgoAPI_Common(*faces)
    assert common.IsDone() and not common.Shape().IsNull()
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(common.Shape(), props, 1e-8)
    expected = pi * (10**2 - 8**2) / abs(sum(miter.normal[i] * miter.directions[0][i] for i in range(3)))
    assert float(props.Mass()) == pytest.approx(expected, rel=1e-6, abs=1e-5)
