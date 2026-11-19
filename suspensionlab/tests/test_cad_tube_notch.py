"""Изолированный CAD-прототип: разделка трубы по наружному объёму корпуса."""
import math
from copy import deepcopy

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepClass3d import BRepClass3d_SolidClassifier  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # noqa: E402
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_IN, TopAbs_OUT  # noqa: E402

from suspensionlab.core.cad_tube_notch import TubeNotchError, notch_tube_against_housing  # noqa: E402
from suspensionlab.model.entities import Project  # noqa: E402
from suspensionlab.model.scheme_arm_assembly import make_scheme_arm_assembly, set_assembly_axis  # noqa: E402


def document(*, rear=(100, 0, 0), outer=(0, 100, 0), radius=14, length=24):
    project = Project.create_default()
    for code, xyz in {'lca_f_in': (0, 0, 0), 'lca_r_in': rear, 'lbj': outer}.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    return make_scheme_arm_assembly(project, 10, 2, {'axis': 'x', 'outer_radius_mm': radius,
                                                       'bore_radius_mm': 7, 'length_mm': length})


def volume(shape):
    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return properties.Mass()


def test_saddle_cuts_whole_housing_envelope_not_just_the_hollow_wall():
    doc = document()
    initial = deepcopy(doc)
    result = notch_tube_against_housing(doc, 'tube_front', 'housing_front')
    assert doc == initial
    assert result.tube_id == 'tube_front' and result.housing_id == 'housing_front'
    assert BRepCheck_Analyzer(result.shape).IsValid()
    assert result.original_volume_mm3 == pytest.approx(math.pi * (10**2 - 8**2) * 100, rel=1e-7)
    assert 0 < result.remaining_volume_mm3 < result.original_volume_mm3
    assert result.removed_volume_mm3 == pytest.approx(result.original_volume_mm3 - result.remaining_volume_mm3)
    # These points lie inside the tube wall (radius 9), one before and one
    # beyond the cylinder surface. The former is also inside the housing bore:
    # subtracting only the hollow housing material would leave it behind.
    assert BRepClass3d_SolidClassifier(result.shape, gp_Pnt(9, 5, 0), 1e-7).State() == TopAbs_OUT
    assert BRepClass3d_SolidClassifier(result.shape, gp_Pnt(9, 15, 0), 1e-7).State() == TopAbs_IN
    envelope = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(-12, 0, 0), gp_Dir(1, 0, 0)), 14, 24).Shape()
    intersection = BRepAlgoAPI_Common(result.shape, envelope)
    assert intersection.IsDone()
    assert volume(intersection.Shape()) == pytest.approx(0, abs=1e-5)


@pytest.mark.parametrize('axis', ['x', 'y', 'z'])
def test_axis_and_housing_selection(axis):
    doc = set_assembly_axis(document(), axis)
    result = notch_tube_against_housing(doc, 'tube_front', 'housing_front')
    assert result.removed_volume_mm3 > 0 and BRepCheck_Analyzer(result.shape).IsValid()
    assert result.remaining_volume_mm3 + result.removed_volume_mm3 == pytest.approx(result.original_volume_mm3)


@pytest.mark.parametrize(('tube', 'housing'), [('tube_front', 'housing_front'), ('tube_rear', 'housing_rear')])
def test_oblique_tube_with_optional_plate_does_not_change_document(tube, housing):
    from suspensionlab.model.scheme_arm_assembly import make_plate, set_assembly_plate

    doc = document(outer=(35, 100, 40))
    doc = set_assembly_plate(doc, make_plate(60, 50, 5, 10),
                             {'normal': 'z', 'offset_mm': [0, 0, 0]})
    initial = deepcopy(doc)
    result = notch_tube_against_housing(doc, tube, housing)
    assert doc == initial and BRepCheck_Analyzer(result.shape).IsValid()
    assert result.removed_volume_mm3 > 0
    assert result.remaining_volume_mm3 < result.original_volume_mm3


def test_no_overlap_invalid_pair_and_no_mutation():
    doc = document()
    initial = deepcopy(doc)
    with pytest.raises(TubeNotchError, match='no_overlap'):
        notch_tube_against_housing(doc, 'tube_front', 'housing_rear')
    with pytest.raises(TubeNotchError, match='unsupported_pair'):
        notch_tube_against_housing(doc, 'housing_front', 'tube_front')
    assert doc == initial


def test_tangency_is_not_a_cut():
    # Housing along X ends exactly at x=10, the outer tangent of the tube.
    with pytest.raises(TubeNotchError, match='no_overlap'):
        notch_tube_against_housing(document(rear=(22, 0, 0)), 'tube_front', 'housing_rear')


def test_cut_must_not_remove_all_or_split_tube():
    with pytest.raises(TubeNotchError, match='empty_or_split'):
        notch_tube_against_housing(document(radius=500, length=500), 'tube_front', 'housing_front')
    with pytest.raises(TubeNotchError, match='empty_or_split'):
        notch_tube_against_housing(document(rear=(0, 50, 0)), 'tube_front', 'housing_rear')


def plate_document(normal='y', offset=(0, 0, 0), *, hole=9.5, thickness=5):
    from suspensionlab.model.scheme_arm_assembly import make_plate, set_assembly_plate

    return set_assembly_plate(document(), make_plate(60, 60, thickness, hole),
                              {'normal': normal, 'offset_mm': list(offset)})


def test_plate_cut_uses_material_and_preserves_tube_inside_hole():
    from suspensionlab.core.cad_kim_prototype import _place_scheme_arm_plate
    from suspensionlab.core.cad_tube_notch import notch_tube_against_plate

    doc = plate_document()
    original = deepcopy(doc)
    result = notch_tube_against_plate(doc, 'tube_front')
    assert doc == original and result.cutter_id == 'ball_plate'
    assert BRepCheck_Analyzer(result.shape).IsValid()
    # At y=99 the plate covers the annulus outside its radius 9.5 hole.
    assert BRepClass3d_SolidClassifier(result.shape, gp_Pnt(9.8, 99, 0), 1e-7).State() == TopAbs_OUT
    assert BRepClass3d_SolidClassifier(result.shape, gp_Pnt(8.5, 99, 0), 1e-7).State() == TopAbs_IN
    assert result.removed_volume_mm3 == pytest.approx(math.pi * (10**2 - 9.5**2) * 2.5, rel=1e-6)
    intersection = BRepAlgoAPI_Common(result.shape, _place_scheme_arm_plate(doc))
    assert intersection.IsDone() and volume(intersection.Shape()) == pytest.approx(0, abs=1e-5)


@pytest.mark.parametrize('normal', ['x', 'y', 'z'])
@pytest.mark.parametrize('tube', ['tube_front', 'tube_rear'])
def test_plate_placement_and_selection(normal, tube):
    from suspensionlab.core.cad_assembly_projection import bounds_for_shape
    from suspensionlab.core.cad_kim_prototype import _place_scheme_arm_plate
    from suspensionlab.core.cad_tube_notch import notch_tube_against_plate

    doc = plate_document(normal, (0, -10, 0))
    before = deepcopy(doc)
    bounds = bounds_for_shape(_place_scheme_arm_plate(doc))
    # Plate is centred at LBJ plus offset; normal is the thin axis.
    spans = [bounds[i + 3] - bounds[i] for i in range(3)]
    assert spans[['x', 'y', 'z'].index(normal)] == pytest.approx(5)
    assert [(bounds[i + 3] + bounds[i]) / 2 for i in range(3)] == pytest.approx([0, 90, 0])
    result = notch_tube_against_plate(doc, tube)
    assert result.removed_volume_mm3 > 0 and BRepCheck_Analyzer(result.shape).IsValid()
    assert doc == before


def test_plate_absence_tangency_and_split_rejected():
    from suspensionlab.core.cad_tube_notch import notch_tube_against_plate

    with pytest.raises(TubeNotchError, match='missing_plate'):
        notch_tube_against_plate(document(), 'tube_front')
    with pytest.raises(TubeNotchError, match='no_overlap'):
        notch_tube_against_plate(plate_document('y', (0, 2.5, 0), hole=5), 'tube_front')
    with pytest.raises(TubeNotchError, match='no_overlap'):
        notch_tube_against_plate(plate_document('y', (0, 100, 0)), 'tube_front')
    with pytest.raises(TubeNotchError, match='empty_or_split'):
        notch_tube_against_plate(plate_document('y', (0, -50, 0), hole=5), 'tube_front')
    with pytest.raises(TubeNotchError, match='empty_or_split'):
        notch_tube_against_plate(plate_document('y', (0, -50, 0), hole=5, thickness=500), 'tube_front')
    with pytest.raises(TubeNotchError, match='unsupported_pair'):
        notch_tube_against_plate(plate_document(), 'housing_front')


def test_tube_cut_uses_finite_outer_envelope_not_hollow_material():
    from suspensionlab.core.cad_tube_notch import notch_tube_against_tube

    # Front tube lies on Y, rear tube on X; the two share their final endpoint.
    doc = document(rear=(100, 100, 0))
    before = deepcopy(doc)
    result = notch_tube_against_tube(doc, 'tube_front', 'tube_rear')
    assert doc == before
    assert (result.tube_id, result.cutter_id) == ('tube_front', 'tube_rear')
    assert BRepCheck_Analyzer(result.shape).IsValid()
    # (9, 95, 0) is within the wall of the target but also in the bore of
    # the cutter (distance 5 from its axis); that material must be removed.
    for point, expected in [((9, 95, 0), TopAbs_OUT), ((-9, 95, 0), TopAbs_IN),
                            ((9, 80, 0), TopAbs_IN)]:
        assert BRepClass3d_SolidClassifier(result.shape, gp_Pnt(*point), 1e-7).State() == expected
    envelope = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(100, 100, 0), gp_Dir(-1, 0, 0)), 10, 100).Shape()
    intersection = BRepAlgoAPI_Common(result.shape, envelope)
    assert intersection.IsDone() and volume(intersection.Shape()) == pytest.approx(0, abs=1e-5)
    assert result.original_volume_mm3 == pytest.approx(math.pi * (10**2 - 8**2) * 100)
    assert 0 < result.removed_volume_mm3 < result.original_volume_mm3


@pytest.mark.parametrize(('tube', 'cutter'), [('tube_front', 'tube_rear'), ('tube_rear', 'tube_front')])
@pytest.mark.parametrize(('rear', 'outer'), [((100, 100, 0), (0, 100, 0)), ((100, 0, 0), (35, 100, 40))])
def test_cut_both_tube_directions_with_different_diameters(tube, cutter, rear, outer):
    from suspensionlab.core.cad_tube_notch import notch_tube_against_tube
    from suspensionlab.model.scheme_arm_assembly import edit_assembly_part

    doc = edit_assembly_part(document(rear=rear, outer=outer), 'tube_rear',
                             {'radius_mm': 7, 'wall_mm': 1.5})
    original = deepcopy(doc)
    result = notch_tube_against_tube(doc, tube, cutter)
    assert doc == original and BRepCheck_Analyzer(result.shape).IsValid()
    assert result.cutter_id == cutter and result.tube_id == tube
    assert result.remaining_volume_mm3 > 0 and result.removed_volume_mm3 > 0
    assert result.original_volume_mm3 == pytest.approx(result.remaining_volume_mm3 + result.removed_volume_mm3)


def test_tube_cut_rejects_self_butt_contact_and_fully_removed_tube():
    from suspensionlab.core.cad_tube_notch import notch_tube_against_tube

    doc = document()
    original = deepcopy(doc)
    with pytest.raises(TubeNotchError, match='same_tube'):
        notch_tube_against_tube(doc, 'tube_front', 'tube_front')
    with pytest.raises(TubeNotchError, match='unsupported_pair'):
        notch_tube_against_tube(doc, 'tube_front', 'ball_plate')
    # The two straight tube endpoints meet at y=100, but have no volume in common.
    with pytest.raises(TubeNotchError, match='no_overlap'):
        notch_tube_against_tube(document(rear=(0, 200, 0)), 'tube_front', 'tube_rear')
    # The shorter coaxial target is entirely within the longer cutter envelope.
    with pytest.raises(TubeNotchError, match='empty_or_split'):
        notch_tube_against_tube(document(rear=(0, -100, 0)), 'tube_front', 'tube_rear')
    assert doc == original


def test_tube_cut_does_not_extend_the_cutter_beyond_its_end():
    from suspensionlab.core.cad_tube_notch import notch_tube_against_tube

    # Rear occupies y=50..100, front y=0..100. Only that finite half is removed.
    result = notch_tube_against_tube(document(rear=(0, 50, 0)), 'tube_front', 'tube_rear')
    assert BRepClass3d_SolidClassifier(result.shape, gp_Pnt(9, 25, 0), 1e-7).State() == TopAbs_IN
    assert BRepClass3d_SolidClassifier(result.shape, gp_Pnt(9, 75, 0), 1e-7).State() == TopAbs_OUT
    assert result.removed_volume_mm3 == pytest.approx(math.pi * (10**2 - 8**2) * 50, rel=1e-7)
