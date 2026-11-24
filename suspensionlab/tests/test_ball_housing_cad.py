"""Инварианты опытной стыковки: геометрия, а не оценка прочности."""
from copy import deepcopy

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_SOLID  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402

from suspensionlab.core.cad_ball_housing import build_ball_housing_tubes  # noqa: E402
from suspensionlab.model.ball_housing import BallHousingError, validate_ball_housing  # noqa: E402
from suspensionlab.model.fixed_arm_skeleton import (  # noqa: E402
    capture_fixed_arm,
    fixed_arm_tube_document,
    preview_fixed_arm,
)
from suspensionlab.model.templates import load_template  # noqa: E402


def parameters():
    return {'outer_diameter_mm': 120, 'bore_diameter_mm': 30, 'length_mm': 200,
            'axis': [0, 0, 1], 'offset_mm': [10, -30, 12]}


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1e-8)
    return abs(float(props.Mass()))


def make_document(bent=()):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, 0, 0)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    bends = {}
    for index, leg in enumerate(('front', 'rear')):
        if leg in bent:
            vertex = [(anchors[index][i] + anchors[2][i]) / 2 for i in range(3)]
            vertex[2] += 50 if index == 0 else -40
            bends[leg] = {'vertex_mm': vertex, 'radius_mm': 20}
    return fixed_arm_tube_document(snapshot, project, 10, 2, bends)


@pytest.mark.parametrize('bent', [(), ('front',), ('rear',), ('front', 'rear')])
def test_center_housing_is_separate_and_both_tubes_end_at_it(bent):
    document, data = make_document(bent), parameters()
    before = deepcopy((document, data))
    front, rear, housing = build_ball_housing_tubes(document, data)
    for shape in (front, rear, housing):
        assert BRepCheck_Analyzer(shape).IsValid()
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        solids = 0
        while explorer.More():
            solids += 1
            explorer.Next()
        assert solids == 1
        assert volume(shape) > 0
    for tube in (front, rear):
        contact = BRepExtrema_DistShapeShape(tube, housing)
        assert contact.IsDone() and contact.Value() < 1e-6
        common = BRepAlgoAPI_Common(tube, housing)
        assert common.IsDone() and volume(common.Shape()) < 1e-5
    common = BRepAlgoAPI_Common(front, rear)
    assert common.IsDone() and volume(common.Shape()) < 1e-5
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(housing, props, 1e-8)
    actual = props.CentreOfMass()
    point = document['parts'][0]['geometry']['source']['coordinates_mm'][2]
    center = [point[i] + data['offset_mm'][i] for i in range(3)]
    assert [actual.X(), actual.Y(), actual.Z()] == pytest.approx(center, abs=1e-6)
    assert (document, data) == before


@pytest.mark.parametrize('change', [
    {'outer_diameter_mm': 60},  # legs overlap before reaching the cylinder
    {'length_mm': 5},  # tube would hit an end face
    {'outer_diameter_mm': 1000},  # cylinder reaches support/bend
    {'axis': [0, 1, 0]},  # tube would enter an end face
])
def test_invalid_approach_is_rejected(change):
    data = parameters()
    data.update(change)
    with pytest.raises(BallHousingError):
        build_ball_housing_tubes(make_document(), data)


@pytest.mark.parametrize('change', [
    {'outer_diameter_mm': float('nan')}, {'outer_diameter_mm': 10**1000},
    {'bore_diameter_mm': 120}, {'axis': [0, 0, 0]}, {'axis': [1, 2]},
    {'offset_mm': [0, float('inf'), 0]}, {'length_mm': True},
])
def test_invalid_parameters_are_rejected(change):
    data = parameters()
    data.update(change)
    with pytest.raises(BallHousingError):
        validate_ball_housing(data)


def test_preview_and_worker_keep_three_distinct_parts_and_reject_invalid_geometry():
    from suspensionlab.core.cad_kim_prototype import build_fixed_arm_housing_preview
    from suspensionlab.core.cad_transport import CadPreviewError
    from suspensionlab.core.cad_weldment_job import WeldmentCadJob
    from suspensionlab.model.fixed_arm_housings import HousingError, make_housing_preview

    document = make_housing_preview(make_document(), None, ball_housing=parameters())
    shape = build_fixed_arm_housing_preview(document)
    assert BRepCheck_Analyzer(shape).IsValid()
    mesh = WeldmentCadJob().run(document, deviation=2)
    assert mesh.part_names == ('tube_front', 'tube_rear', 'ball_housing')
    assert set(mesh.triangle_parts.tolist()) == {0, 1, 2}
    invalid = parameters()
    invalid['outer_diameter_mm'] = 60
    failed = make_housing_preview(make_document(), None, ball_housing=invalid)
    with pytest.raises(CadPreviewError) as exc:
        WeldmentCadJob().run(failed, deviation=2)
    assert exc.value.code == 'ball_housing_failed'
    with pytest.raises(HousingError):
        make_housing_preview(make_document(), None, tube_joint={'target': 'miter', 'radial_clearance_mm': 0},
                             ball_housing=parameters())


def test_preview_with_internal_housings_and_notches():
    from test_fixed_arm_housings import housings

    from suspensionlab.core.cad_kim_prototype import build_fixed_arm_housing_preview
    from suspensionlab.core.cad_weldment_job import WeldmentCadJob
    from suspensionlab.model.fixed_arm_housings import make_housing_preview

    document = make_housing_preview(make_document(), housings(), {'front': 0, 'rear': 0},
                                    ball_housing=parameters())
    shape = build_fixed_arm_housing_preview(document)
    assert BRepCheck_Analyzer(shape).IsValid()
    mesh = WeldmentCadJob().run(document, deviation=2)
    assert mesh.part_names == ('tube_front', 'tube_rear', 'housing_front', 'housing_rear', 'ball_housing')


def test_later_cut_must_not_damage_the_central_joint():
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Pnt

    from suspensionlab.core.cad_ball_housing import validate_ball_housing_contacts

    document, data = make_document(), parameters()
    front, rear, _ = build_ball_housing_tubes(document, data)
    # Put a cutter at the known contact vicinity of the front tube, not at
    # the distant internal support. The guard must not accept a damaged end.
    center = document['parts'][0]['geometry']['source']['coordinates_mm'][2]
    center = [center[i] + data['offset_mm'][i] for i in range(3)]
    start = document['parts'][0]['geometry']['source']['coordinates_mm'][0]
    length = sum((start[i] - center[i]) ** 2 for i in range(3)) ** .5
    hit = [center[i] + (start[i] - center[i]) / length * 65 for i in range(3)]
    cut = BRepAlgoAPI_Cut(front, BRepPrimAPI_MakeSphere(gp_Pnt(*hit), 15).Shape())
    assert cut.IsDone()
    with pytest.raises(BallHousingError, match='повреждает'):
        validate_ball_housing_contacts(document, data, [front, rear], [cut.Shape(), rear])


def test_tilted_and_reversed_axis_build():
    for axis in ([.1, .05, 1], [0, 0, -1]):
        data = parameters()
        data['axis'] = axis
        shapes = build_ball_housing_tubes(make_document(('front', 'rear')), data)
        assert all(BRepCheck_Analyzer(shape).IsValid() for shape in shapes)


def test_automatic_cut_candidates_cannot_drop_the_central_housing():
    from suspensionlab.core.fixed_arm_plans import validate_plan_request
    from suspensionlab.core.fixed_arm_suggestions import candidate_document, validate_request
    from suspensionlab.model.fixed_arm_housings import make_housing_preview

    doc = make_housing_preview(make_document(), None, ball_housing=parameters())
    with pytest.raises(ValueError, match='ball_housing_unsupported'):
        candidate_document(doc, 'joint', 'front', 1.)
    with pytest.raises(ValueError, match='ball_housing_unsupported'):
        validate_request({'document': doc, 'left': 'tube_front', 'right': 'tube_rear', 'minimum_mm': 0.})
    with pytest.raises(ValueError, match='ball_housing_unsupported'):
        validate_plan_request({'document': doc, 'requirements': {}})
