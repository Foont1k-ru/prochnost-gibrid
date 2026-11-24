"""Общее геометрическое ядро без подмены расчётного снимка."""
import math

import pytest
from test_free_arm_inner_housings import make_inner

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402

from suspensionlab.core.cad_fixed_arm_miter import (  # noqa: E402
    build_miter_tubes,
    miter_geometry,
    miter_geometry_for_tubes,
    validate_miter_face,
)
from suspensionlab.core.cad_free_arm import _free_arm_geometries, build_free_arm_miter  # noqa: E402
from suspensionlab.core.cad_transport import CadPreviewError  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.fixed_arm_skeleton import (  # noqa: E402
    capture_fixed_arm,
    fixed_arm_tube_document,
    preview_fixed_arm,
)
from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft  # noqa: E402
from suspensionlab.model.free_arm_miter import FreeArmMiterDraft  # noqa: E402
from suspensionlab.model.free_arm_miter_io import to_data  # noqa: E402
from suspensionlab.model.templates import load_template  # noqa: E402


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1e-8)
    return abs(float(props.Mass()))


@pytest.mark.parametrize('bent', [(), ('front',), ('rear',), ('front', 'rear')])
def test_independent_and_snapshot_share_exact_geometry_for_same_points(bent):
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, 0, 0)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    bends = {}
    for index, leg in enumerate(('front', 'rear')):
        if leg in bent:
            v = [(anchors[index][i] + anchors[2][i]) / 2 for i in range(3)]
            v[2] += 50 if index == 0 else -40
            bends[leg] = {'vertex_mm': v, 'radius_mm': 20}
    fixed = fixed_arm_tube_document(snapshot, project, 10, 2, bends)
    arm = FreeArmDraft(*anchors, 10, 2,
                       *(FreeArmBend(bends[leg]['vertex_mm'], 20) if leg in bends else None
                         for leg in ('front', 'rear')))
    geometry = miter_geometry_for_tubes(arm.anchors, _free_arm_geometries(arm))
    assert geometry == miter_geometry(fixed)
    _, independent = build_free_arm_miter(FreeArmMiterDraft(arm))
    expected = build_miter_tubes(fixed)
    for index, (actual, prior) in enumerate(zip(independent, expected, strict=True)):
        assert BRepCheck_Analyzer(actual).IsValid()
        validate_miter_face(actual, geometry, _free_arm_geometries(arm)[index], index)
        assert volume(actual) == pytest.approx(volume(prior), rel=1e-7)
        for a, b in ((actual, prior), (prior, actual)):
            diff = BRepAlgoAPI_Cut(a, b)
            assert diff.IsDone() and volume(diff.Shape()) < 1e-5
    common = BRepAlgoAPI_Common(*independent)
    assert common.IsDone() and volume(common.Shape()) < 1e-5
    distance = BRepExtrema_DistShapeShape(*independent)
    assert distance.IsDone() and distance.Value() < 1e-6


@pytest.mark.parametrize('inner', [False, True])
def test_real_worker_with_optional_inner_housings(inner):
    data = make_inner()
    draft = FreeArmMiterDraft(data.arm, data.housings if inner else None)
    _, components = build_free_arm_miter(draft)
    assert len(components) == (4 if inner else 2)
    mesh = WeldmentCadJob().run(to_data(draft))
    assert mesh.part_names == (('tube_front', 'tube_rear', 'housing_front', 'housing_rear') if inner else
                               ('tube_front', 'tube_rear'))
    assert mesh.all_parts_present()


def test_impossible_miter_worker_error_is_explicit_and_no_mesh():
    arm = FreeArmDraft((0, 0, 0), (0, .1, 0), (300, 100, 10), 10, 2)
    with pytest.raises(CadPreviewError) as error:
        WeldmentCadJob().run(to_data(FreeArmMiterDraft(arm)))
    assert error.value.code == 'tube_joint_miter_failed'


def test_short_end_rejected_before_cad():
    arm = FreeArmDraft((0, 0, 0), (0, 1, 0), (300, 100, 10), 10, 2)
    with pytest.raises(ValueError):
        miter_geometry_for_tubes(arm.anchors, _free_arm_geometries(arm))
    assert math.isfinite(arm.radius_mm)


def test_later_inner_cut_cannot_damage_the_common_miter_face(monkeypatch):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Pnt

    from suspensionlab.core import cad_inner_housings
    from suspensionlab.core.cad_fixed_arm_miter import MiterError

    base = make_inner()
    draft = FreeArmMiterDraft(base.arm, base.housings)
    real = cad_inner_housings.build_inner_housings_and_notch
    def damaged(tubes, centers, data, notches):
        result, housings = real(tubes, centers, data, notches)
        cut = BRepAlgoAPI_Cut(result[0], BRepPrimAPI_MakeSphere(gp_Pnt(*draft.arm.outer_mm), 15).Shape())
        assert cut.IsDone()
        result[0] = cut.Shape()
        return result, housings
    monkeypatch.setattr(cad_inner_housings, 'build_inner_housings_and_notch', damaged)
    with pytest.raises(MiterError, match='Поверхность стыка'):
        build_free_arm_miter(draft)


@pytest.mark.parametrize('bent', [('front',), ('rear',), ('front', 'rear')])
def test_miter_and_bent_tubes_keep_faces_after_inner_notches(bent):
    base = make_inner(bent=bent)
    draft = FreeArmMiterDraft(base.arm, base.housings)
    _, components = build_free_arm_miter(draft)
    geometry = miter_geometry_for_tubes(base.arm.anchors, _free_arm_geometries(base.arm))
    for index, tube in enumerate(components[:2]):
        validate_miter_face(tube, geometry, _free_arm_geometries(base.arm)[index], index)
    mesh = WeldmentCadJob().run(to_data(draft))
    assert mesh.part_names == ('tube_front', 'tube_rear', 'housing_front', 'housing_rear')
    assert mesh.all_parts_present()


def test_miter_worker_does_not_mislabel_memory_failure(monkeypatch, tmp_path):
    from suspensionlab.core import cad_free_arm
    from suspensionlab.core.cad_weldment_worker import create_grouped_mesh
    from suspensionlab.core.cad_worker import CadWorkerError
    from suspensionlab.model.free_arm_miter_io import write_free_arm_miter

    path = write_free_arm_miter(tmp_path / 'miter.slarm', FreeArmMiterDraft(make_inner().arm))
    def fail(_draft):
        raise MemoryError('test')
    monkeypatch.setattr(cad_free_arm, 'build_free_arm_miter', fail)
    with pytest.raises(CadWorkerError) as error:
        create_grouped_mesh(path, 2.)
    assert error.value.code == 'memory'
