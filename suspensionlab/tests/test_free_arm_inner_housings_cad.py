"""Конечная подрезка и транспорт независимых корпусов через реальное CAD-ядро."""
from dataclasses import replace

import pytest
from test_free_arm_inner_housings import make_inner

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder  # noqa: E402
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402

from suspensionlab.core.cad_free_arm import build_free_arm_inner_housings  # noqa: E402
from suspensionlab.core.cad_kim_prototype import FixedArmNotchError  # noqa: E402
from suspensionlab.core.cad_transport import CadPreviewError  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.free_arm_inner_housings_io import to_data  # noqa: E402


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1e-8)
    return abs(props.Mass())


@pytest.mark.parametrize('ball,bent', [(False, ()), (False, ('front',)), (True, ()), (True, ('front', 'rear'))])
def test_finite_cut_and_isolated_worker(ball, bent):
    draft = make_inner(ball=ball, bent=bent)
    _, parts = build_free_arm_inner_housings(draft)
    assert len(parts) == (5 if ball else 4)
    for index, leg in enumerate(('front', 'rear')):
        spec = getattr(draft.housings, leg)
        clearance = getattr(draft.housings, f'{leg}_clearance_mm')
        center = draft.arm.anchors[index]
        origin = (center[0], center[1], center[2] - spec.length_mm / 2)
        cutter = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*origin), gp_Dir(0, 0, 1)),
                                           spec.outer_diameter_mm / 2 + clearance, spec.length_mm).Shape()
        common = BRepAlgoAPI_Common(parts[index], cutter)
        assert common.IsDone() and volume(common.Shape()) < 1e-5
    mesh = WeldmentCadJob().run(to_data(draft))
    assert mesh.part_names == (('tube_front', 'tube_rear', 'housing_front', 'housing_rear', 'ball_housing')
                               if ball else ('tube_front', 'tube_rear', 'housing_front', 'housing_rear'))
    assert mesh.all_parts_present()


def test_bad_cut_reports_failure_not_partial_preview():
    draft = make_inner()
    # A very long axis-aligned housing removes the entire branch.
    front = replace(draft.housings.front, outer_diameter_mm=1000, length_mm=2000)
    invalid = replace(draft, housings=replace(draft.housings, front=front))
    with pytest.raises(FixedArmNotchError) as error:
        build_free_arm_inner_housings(invalid)
    assert error.value.leg == 'front'
    with pytest.raises(CadPreviewError, match='notch_front'):
        WeldmentCadJob().run(to_data(invalid))


def test_only_selected_cut_uses_finite_oblique_envelope():
    from math import hypot

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    draft = make_inner(cuts=False)
    front = replace(draft.housings.front, axis=(1, 2, 3), length_mm=70)
    uncut = replace(draft, housings=replace(draft.housings, front=front))
    cut = replace(uncut, housings=replace(uncut.housings, front_clearance_mm=1.25))
    _, old = build_free_arm_inner_housings(uncut)
    _, new = build_free_arm_inner_housings(cut)
    removed = BRepAlgoAPI_Cut(old[0], new[0])
    assert removed.IsDone() and volume(removed.Shape()) > 1
    direction = tuple(v / hypot(*front.axis) for v in front.axis)
    center = draft.arm.front_mm
    origin = tuple(center[i] - direction[i] * front.length_mm / 2 for i in range(3))
    envelope = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*origin), gp_Dir(*direction)),
                                         front.outer_diameter_mm / 2 + 1.25, front.length_mm).Shape()
    outside = BRepAlgoAPI_Cut(removed.Shape(), envelope)
    assert outside.IsDone() and volume(outside.Shape()) < 1e-5
    assert volume(old[1]) == pytest.approx(volume(new[1]), rel=1e-8)
    assert volume(old[2]) == pytest.approx(volume(new[2]), rel=1e-8)


def test_one_inner_cut_with_central_body_and_no_notches_remain_independent():
    draft = make_inner(ball=True)
    one = replace(draft, housings=replace(draft.housings, rear_clearance_mm=None))
    none = replace(one, housings=replace(one.housings, front_clearance_mm=None))
    _, before = build_free_arm_inner_housings(none)
    _, after = build_free_arm_inner_housings(one)
    assert volume(after[0]) < volume(before[0])
    assert volume(after[1]) == pytest.approx(volume(before[1]), rel=1e-8)
    assert volume(after[4]) == pytest.approx(volume(before[4]), rel=1e-8)


def test_central_failure_is_preserved_in_v3_worker():
    from suspensionlab.model.ball_housing import BallHousingError

    draft = make_inner(ball=True)
    draft = replace(draft, ball_housing=replace(draft.ball_housing, length_mm=5))
    with pytest.raises(BallHousingError):
        build_free_arm_inner_housings(draft)
    with pytest.raises(CadPreviewError) as error:
        WeldmentCadJob().run(to_data(draft))
    assert error.value.code == 'ball_housing_failed'
