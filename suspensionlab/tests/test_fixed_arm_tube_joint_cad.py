"""Подрезка по конечной исходной трубе, без соединения и с явным направлением реза."""
from copy import deepcopy
from math import dist, pi

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # noqa: E402
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopoDS import TopoDS_Iterator  # noqa: E402
from test_fixed_arm_housings import housings  # noqa: E402

from suspensionlab.core.cad_fixed_arm_overlap_job import FixedArmOverlapJob  # noqa: E402
from suspensionlab.core.cad_kim_prototype import (  # noqa: E402
    FixedArmNotchError,
    _fixed_arm_tube_envelope,
    build_fixed_arm_housing_preview,
    build_weldment_tubes_preview,
)
from suspensionlab.core.cad_transport import CadPreviewError  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.bent_tube import make_bend_path  # noqa: E402
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
    return props.Mass()


def parts(shape):
    iterator = TopoDS_Iterator(shape)
    result = []
    while iterator.More():
        result.append(iterator.Value())
        iterator.Next()
    return result


@pytest.mark.parametrize(('target', 'bent_leg', 'with_housings'), [
    ('front', None, False), ('rear', None, False), ('front', 'rear', False),
    ('rear', 'front', False), ('front', 'front', True), ('rear', 'rear', True),
])
def test_selected_tube_cut_against_original_tube_and_geometry_invariants(target, bent_leg, with_housings):
    project = load_template('ring')
    before = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    bends = {}
    if bent_leg is not None:
        start = anchors[('front', 'rear').index(bent_leg)]
        vertex = [(start[i] + anchors[2][i]) / 2 for i in range(3)]
        vertex[2] += 50
        bends[bent_leg] = {'vertex_mm': vertex, 'radius_mm': 20}
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2, bends)
    original = parts(build_weldment_tubes_preview(tubes))
    housing = housings() if with_housings else None
    housing_notches = {'rear': 1.0} if with_housings else None
    joint = {'target': target, 'radial_clearance_mm': 0.5}
    doc = make_housing_preview(tubes, housing, housing_notches, joint)
    result = parts(build_fixed_arm_housing_preview(doc))
    assert len(result) == (4 if with_housings else 2)
    assert all(BRepCheck_Analyzer(shape).IsValid() for shape in result)
    target_index = ('front', 'rear').index(target)
    other_index = 1 - target_index
    assert 0 < volume(result[target_index]) < volume(original[target_index])
    if not with_housings:
        assert volume(result[other_index]) == pytest.approx(volume(original[other_index]), rel=1e-8)
    cutter = _fixed_arm_tube_envelope(tubes['parts'][other_index], 0.5)
    path_length = (make_bend_path(anchors[other_index], bends[bent_leg]['vertex_mm'], anchors[2], 20, 10.5).length
                   if bent_leg == ('front', 'rear')[other_index] else dist(anchors[other_index], anchors[2]))
    assert volume(cutter) == pytest.approx(pi * 10.5**2 * path_length, rel=1e-7)
    intersection = BRepAlgoAPI_Common(result[target_index], cutter)
    assert intersection.IsDone() and abs(volume(intersection.Shape())) < 1e-5
    if with_housings:
        without_joint = parts(build_fixed_arm_housing_preview(make_housing_preview(tubes, housing, housing_notches)))
        for index in (2, 3):
            assert volume(result[index]) == pytest.approx(volume(without_joint[index]), rel=1e-8)
        # A later tube-to-tube cut must not reintroduce a housing overlap.
        spec = housing['rear']
        start = (anchors[1][0], anchors[1][1] + spec['length_mm'] / 2, anchors[1][2])
        envelope = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*start), gp_Dir(0, -1, 0)),
                                            spec['outer_diameter_mm'] / 2 + 1, spec['length_mm']).Shape()
        common = BRepAlgoAPI_Common(result[1], envelope)
        assert common.IsDone() and abs(volume(common.Shape())) < 1e-5
    mesh = WeldmentCadJob().run(doc, deviation=2)
    expected = ('tube_front', 'tube_rear', 'housing_front', 'housing_rear') if with_housings else ('tube_front', 'tube_rear')
    assert mesh.part_names == expected and set(mesh.triangle_parts.tolist()) == set(range(len(expected)))
    overlap = FixedArmOverlapJob().run(doc)
    assert overlap.overlap_mm3 <= overlap.threshold_mm3
    assert project.to_dict() == before


def test_unbuildable_enlarged_bend_rejected_by_cad_worker():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    vertex = [(anchors[0][i] + anchors[2][i]) / 2 for i in range(3)]
    vertex[2] += 50
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2, {'front': {'vertex_mm': vertex, 'radius_mm': 20}})
    doc = make_housing_preview(tubes, None, tube_joint={'target': 'rear', 'radial_clearance_mm': 30})
    with pytest.raises(FixedArmNotchError) as error:
        build_fixed_arm_housing_preview(doc)
    assert error.value.tube_joint and error.value.leg == 'rear'
    with pytest.raises(CadPreviewError) as worker_error:
        WeldmentCadJob().run(doc, deviation=2)
    assert worker_error.value.code == 'tube_joint_rear_failed'
