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
