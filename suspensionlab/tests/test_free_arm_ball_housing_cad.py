"""Геометрическое ядро корпуса для независимых точек; ещё не UI/формат."""
from copy import deepcopy

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_SOLID  # noqa: E402
from OCP.TopExp import TopExp_Explorer  # noqa: E402
from test_ball_housing_cad import make_document, parameters  # noqa: E402

from suspensionlab.core.cad_ball_housing import build_ball_housing_tubes  # noqa: E402
from suspensionlab.core.cad_free_arm import build_free_arm_ball_housing  # noqa: E402
from suspensionlab.model.ball_housing import BallHousingError  # noqa: E402
from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft  # noqa: E402


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1e-8)
    return abs(float(props.Mass()))


def independent(bent=()):
    return FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2,
                        FreeArmBend((150, 20, 50), 20) if 'front' in bent else None,
                        FreeArmBend((150, 180, -40), 20) if 'rear' in bent else None)


@pytest.mark.parametrize('bent', [(), ('front',), ('rear',), ('front', 'rear')])
def test_independent_geometry_is_valid_separate_and_touches_housing(bent):
    draft, data = independent(bent), parameters()
    before = deepcopy(data)
    front, rear, housing = build_free_arm_ball_housing(draft, data)
    for shape in (front, rear, housing):
        assert BRepCheck_Analyzer(shape).IsValid() and volume(shape) > 0
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        count = 0
        while explorer.More():
            count += 1
            explorer.Next()
        assert count == 1
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
    assert [actual.X(), actual.Y(), actual.Z()] == pytest.approx(
        [draft.outer_mm[i] + data['offset_mm'][i] for i in range(3)], abs=1e-6)
    assert data == before


@pytest.mark.parametrize('bent', [(), ('front',), ('rear',), ('front', 'rear')])
def test_adapter_agrees_with_snapshot_geometry_for_identical_explicit_inputs(bent):
    document, data = make_document(bent), parameters()
    geometries = [part['geometry'] for part in document['parts']]
    points = geometries[0]['source']['coordinates_mm']
    bends = [FreeArmBend(g['bend_vertex_mm'], g['bend_radius_mm']) if g['kind'] == 'prototype_arm_bent_tube' else None
             for g in geometries]
    draft = FreeArmDraft(*points, geometries[0]['radius_mm'], geometries[0]['wall_mm'], *bends)
    snapshot = build_ball_housing_tubes(document, data)
    standalone = build_free_arm_ball_housing(draft, data)
    for a, b in zip(snapshot, standalone, strict=True):
        assert volume(a) == pytest.approx(volume(b), rel=1e-8)
        for first, second in ((a, b), (b, a)):
            cut = BRepAlgoAPI_Cut(first, second)
            assert cut.IsDone() and volume(cut.Shape()) < 1e-5


@pytest.mark.parametrize('change', [
    {'outer_diameter_mm': 60}, {'length_mm': 5}, {'outer_diameter_mm': 1000}, {'axis': [310, 70, 22]},
    {'outer_diameter_mm': float('nan')}, {'bore_diameter_mm': 120}, {'axis': [0, 0, 0]},
    {'offset_mm': [0, float('inf'), 0]}, {'length_mm': True},
])
def test_invalid_parameters_or_contact_are_rejected_without_changing_draft(change):
    draft, data = independent(), parameters()
    data.update(change)
    before = deepcopy(data)
    with pytest.raises(BallHousingError):
        build_free_arm_ball_housing(draft, data)
    # nan needs explicit handling because it is unequal to itself.
    if change.get('outer_diameter_mm') != change.get('outer_diameter_mm'):
        assert data['outer_diameter_mm'] != data['outer_diameter_mm']
    else:
        assert data == before
    assert draft == independent()


def test_wrong_draft_type_is_rejected():
    with pytest.raises(ValueError):
        build_free_arm_ball_housing({}, parameters())


@pytest.mark.parametrize('axis', [[0, 1, 0], [0, 0, -1], [.1, .05, 1]])
def test_different_valid_axes_are_not_rejected(axis):
    data = parameters()
    data['axis'] = axis
    shapes = build_free_arm_ball_housing(independent(('front', 'rear')), data)
    assert all(BRepCheck_Analyzer(shape).IsValid() and volume(shape) > 0 for shape in shapes)
