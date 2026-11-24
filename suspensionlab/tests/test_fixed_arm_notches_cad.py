"""Реальная подрезка выбранных труб по конечным наружным объёмам корпусов."""
from copy import deepcopy
from math import hypot

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

from suspensionlab.core.cad_kim_prototype import (  # noqa: E402
    FixedArmNotchError,
    build_fixed_arm_housing_preview,
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
    return props.Mass()


def parts(shape):
    iterator = TopoDS_Iterator(shape)
    result = []
    while iterator.More():
        result.append(iterator.Value())
        iterator.Next()
    return result


@pytest.mark.parametrize(('bent', 'selected'), [(False, {'front': 0.0}),
                                                (True, {'rear': 1.5}),
                                                (True, {'front': 0.5, 'rear': 2.0})])
def test_notch_correct_branch_volume_and_no_remaining_intersection(bent, selected):
    project = load_template('ring')
    before = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    vertex = [(anchors[0][i] + anchors[2][i]) / 2 for i in range(3)]
    vertex[2] += 50
    bends = {'front': {'vertex_mm': vertex, 'radius_mm': 20}} if bent else {}
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2, bends)
    settings = housings()
    original = parts(build_fixed_arm_housing_preview(make_housing_preview(tubes, settings)))
    candidate = make_housing_preview(tubes, settings, selected)
    after = parts(build_fixed_arm_housing_preview(candidate))
    assert len(after) == 4 and all(BRepCheck_Analyzer(part).IsValid() for part in after)
    for i, leg in enumerate(('front', 'rear')):
        assert volume(after[i + 2]) == pytest.approx(volume(original[i + 2]), rel=1e-9)
        if leg not in selected:
            assert volume(after[i]) == pytest.approx(volume(original[i]), rel=1e-9)
            continue
        assert 0 < volume(after[i]) < volume(original[i])
        spec = settings[leg]
        direction = [v / hypot(*spec['axis']) for v in spec['axis']]
        start = [anchors[i][j] - direction[j] * spec['length_mm'] / 2 for j in range(3)]
        cutter = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*start), gp_Dir(*direction)),
                                         spec['outer_diameter_mm'] / 2 + selected[leg], spec['length_mm']).Shape()
        common = BRepAlgoAPI_Common(after[i], cutter)
        assert common.IsDone() and abs(volume(common.Shape())) < 1e-5
    assert project.to_dict() == before
    mesh = WeldmentCadJob().run(candidate, deviation=2)
    assert mesh.part_names == ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    assert mesh.triangle_parts is not None and set(mesh.triangle_parts.tolist()) == {0, 1, 2, 3}


def test_no_overlap_is_reported_in_worker_and_no_partial_preview():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    tube_doc = fixed_arm_tube_document(snapshot, project, 10, 2)
    settings = housings()
    settings['front'].update(outer_diameter_mm=2, bore_diameter_mm=1, length_mm=10,
                             axis=[anchors[2][i] - anchors[0][i] for i in range(3)])
    doc = make_housing_preview(tube_doc, settings, {'front': 0})
    with pytest.raises(FixedArmNotchError, match='no_overlap'):
        build_fixed_arm_housing_preview(doc)
    with pytest.raises(CadPreviewError) as error:
        WeldmentCadJob().run(doc, deviation=2)
    assert error.value.code == 'notch_front_no_overlap'


def test_complete_removal_rejected_instead_of_showing_partial_result():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2)
    settings = housings()
    settings['rear'].update(outer_diameter_mm=4000, bore_diameter_mm=20, length_mm=4000, axis=[0, 0, 1])
    doc = make_housing_preview(tubes, settings, {'rear': 0})
    with pytest.raises(FixedArmNotchError, match='empty_or_split'):
        build_fixed_arm_housing_preview(doc)
    with pytest.raises(CadPreviewError) as error:
        WeldmentCadJob().run(doc, deviation=2)
    assert error.value.code == 'notch_rear_empty_or_split'
