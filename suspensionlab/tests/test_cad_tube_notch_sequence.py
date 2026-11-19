"""Независимая геометрическая проверка последовательной подрезки."""
from copy import deepcopy

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder  # noqa: E402
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402

from suspensionlab.core.cad_tube_notch import (  # noqa: E402
    notch_tube_against_housing,
    notch_tube_against_plate,
    notch_tube_against_tube,
)
from suspensionlab.core.cad_tube_notch_sequence import TubeNotchSequenceError, notch_tube_sequence  # noqa: E402
from suspensionlab.model.entities import Project  # noqa: E402
from suspensionlab.model.scheme_arm_assembly import (  # noqa: E402
    make_plate,
    make_scheme_arm_assembly,
    set_assembly_plate,
)


def document(rear=(100, 100, 0)):
    project = Project.create_default()
    for code, xyz in {'lca_f_in': (0, 0, 0), 'lca_r_in': rear, 'lbj': (0, 100, 0)}.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    assembly = make_scheme_arm_assembly(project, 10, 2, {'axis': 'x', 'outer_radius_mm': 14,
                                                          'bore_radius_mm': 7, 'length_mm': 24})
    return set_assembly_plate(assembly, make_plate(60, 60, 5, 9.5),
                              {'normal': 'z', 'offset_mm': [0, -30, 0]})


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1e-8)
    return props.Mass()


def cut(a, b):
    result = BRepAlgoAPI_Cut(a, b)
    assert result.IsDone() and not result.Shape().IsNull()
    return result.Shape()


def cylinder(start, direction, radius, length):
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*start), gp_Dir(*direction)), radius, length).Shape()


def test_three_cuts_match_independent_finite_shapes():
    doc = document()
    initial = deepcopy(doc)
    order = ['housing_front', 'ball_plate', 'tube_rear']
    result = notch_tube_sequence(doc, 'tube_front', order)
    assert doc == initial and order == ['housing_front', 'ball_plate', 'tube_rear']
    assert BRepCheck_Analyzer(result.shape).IsValid()
    assert [step.cutter_id for step in result.steps] == order
    assert all(step.removed_volume_mm3 > 0 and step.remaining_volume_mm3 > 0 for step in result.steps)
    for previous, following in zip(result.steps, result.steps[1:], strict=False):
        assert previous.remaining_volume_mm3 == pytest.approx(following.input_volume_mm3, rel=1e-8)
    assert result.steps[0].input_volume_mm3 - sum(x.removed_volume_mm3 for x in result.steps) == pytest.approx(
        result.steps[-1].remaining_volume_mm3, rel=1e-8)

    # Construct reference bodies without the notch helpers or placed plate code.
    original = cut(cylinder((0, 0, 0), (0, 1, 0), 10, 100),
                   cylinder((0, 0, 0), (0, 1, 0), 8, 100))
    housing = cylinder((-12, 0, 0), (1, 0, 0), 14, 24)
    plate_box = BRepPrimAPI_MakeBox(gp_Pnt(-30, 40, -2.5), 60, 60, 5).Shape()
    plate = cut(plate_box, cylinder((0, 70, -2.5), (0, 0, 1), 9.5, 5))
    other_tube = cylinder((100, 100, 0), (-1, 0, 0), 10, 100)
    reference = original
    for cutter in (housing, plate, other_tube):
        reference = cut(reference, cutter)
        intersection = BRepAlgoAPI_Common(result.shape, cutter)
        assert intersection.IsDone() and volume(intersection.Shape()) == pytest.approx(0, abs=1e-5)
    assert volume(cut(result.shape, reference)) == pytest.approx(0, abs=1e-4)
    assert volume(cut(reference, result.shape)) == pytest.approx(0, abs=1e-4)


def test_order_is_explicit_and_overlapping_cutters_change_step_volumes():
    doc = document()
    first = notch_tube_sequence(doc, 'tube_front', ['ball_plate', 'tube_rear'])
    second = notch_tube_sequence(doc, 'tube_front', ['tube_rear', 'ball_plate'])
    assert [x.cutter_id for x in first.steps] == ['ball_plate', 'tube_rear']
    assert [x.cutter_id for x in second.steps] == ['tube_rear', 'ball_plate']
    # The cutters overlap: which one removes that shared portion depends on order.
    assert first.steps[0].removed_volume_mm3 > second.steps[1].removed_volume_mm3
    assert second.steps[0].removed_volume_mm3 > first.steps[1].removed_volume_mm3
    assert first.steps[-1].remaining_volume_mm3 == pytest.approx(second.steps[-1].remaining_volume_mm3, rel=1e-6)


@pytest.mark.parametrize('cutter', ['housing_front', 'ball_plate', 'tube_rear'])
def test_one_step_matches_existing_single_cut(cutter):
    doc = document()
    if cutter == 'housing_front':
        single = notch_tube_against_housing(doc, 'tube_front', cutter)
    elif cutter == 'ball_plate':
        single = notch_tube_against_plate(doc, 'tube_front')
    else:
        single = notch_tube_against_tube(doc, 'tube_front', cutter)
    multi = notch_tube_sequence(doc, 'tube_front', [cutter])
    assert multi.steps[0].removed_volume_mm3 == pytest.approx(single.removed_volume_mm3, rel=1e-8)
    assert volume(cut(multi.shape, single.shape)) == pytest.approx(0, abs=1e-5)
    assert volume(cut(single.shape, multi.shape)) == pytest.approx(0, abs=1e-5)


def test_later_cut_without_remaining_overlap_refuses_entire_sequence():
    # Both housings intersect the original tube, but their envelopes cover the
    # same material of this tube; the second cut is no longer meaningful.
    doc = document(rear=(1, 0, 0))
    before = deepcopy(doc)
    assert notch_tube_against_housing(doc, 'tube_front', 'housing_front').removed_volume_mm3 > 0
    assert notch_tube_against_housing(doc, 'tube_front', 'housing_rear').removed_volume_mm3 > 0
    with pytest.raises(TubeNotchSequenceError, match='no_overlap') as error:
        notch_tube_sequence(doc, 'tube_front', ['housing_front', 'housing_rear'])
    assert (error.value.step_index, error.value.cutter_id) == (1, 'housing_rear')
    assert not hasattr(error.value, 'shape') and doc == before


def test_final_residual_check_rejects_false_success(monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence as sequence
    from suspensionlab.core.cad_tube_notch import TubeNotch

    def false_cut(shape, cutter, tube_id, cutter_id):
        return TubeNotch(tube_id, cutter_id, shape, 100., 90., 10.)
    monkeypatch.setattr(sequence, '_cut_tube', false_cut)
    with pytest.raises(TubeNotchSequenceError, match='invalid_result') as error:
        sequence.notch_tube_sequence(document(), 'tube_front', ['housing_front'])
    assert error.value.step_index == 0 and error.value.cutter_id == 'housing_front'


def test_sequential_cuts_also_work_on_rear_tube():
    doc = document()
    before = deepcopy(doc)
    sequence = notch_tube_sequence(doc, 'tube_rear', ('housing_rear', 'ball_plate', 'tube_front'))
    assert doc == before and sequence.tube_id == 'tube_rear'
    assert [s.cutter_id for s in sequence.steps] == ['housing_rear', 'ball_plate', 'tube_front']
    assert all(s.removed_volume_mm3 > 0 for s in sequence.steps)
    assert BRepCheck_Analyzer(sequence.shape).IsValid()


def test_cutter_construction_failure_has_step_and_no_partial_result(monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence as sequence

    def failed(*args):
        raise RuntimeError('CAD failure')
    monkeypatch.setattr(sequence, '_tube_envelope', failed)
    doc = document()
    before = deepcopy(doc)
    with pytest.raises(TubeNotchSequenceError, match='unexpected') as error:
        sequence.notch_tube_sequence(doc, 'tube_front', ['housing_front', 'tube_rear'])
    assert (error.value.step_index, error.value.cutter_id) == (1, 'tube_rear')
    assert not hasattr(error.value, 'shape') and doc == before


def test_four_different_cutters_in_explicit_order():
    doc = document(rear=(20, 50, 0))
    initial = deepcopy(doc)
    order = ['housing_front', 'housing_rear', 'ball_plate', 'tube_rear']
    result = notch_tube_sequence(doc, 'tube_front', order)
    assert [s.cutter_id for s in result.steps] == order
    assert all(s.removed_volume_mm3 > 0 for s in result.steps)
    assert result.steps[-1].remaining_volume_mm3 > 0 and BRepCheck_Analyzer(result.shape).IsValid()
    assert doc == initial
