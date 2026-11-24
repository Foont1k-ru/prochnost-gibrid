"""Сравнение независимой подрезки с расчётным адаптером при одинаковых точках."""
from copy import deepcopy

import pytest
from test_fixed_arm_housings import housings

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopoDS import TopoDS_Iterator  # noqa: E402
from test_free_arm_housing_io import make_draft  # noqa: E402

from suspensionlab.core.cad_free_arm import (  # noqa: E402
    _free_arm_geometries,
    build_free_arm_tube_joint,
    build_free_arm_tubes,
)
from suspensionlab.core.cad_kim_prototype import build_fixed_arm_housing_preview  # noqa: E402
from suspensionlab.core.cad_transport import CadPreviewError  # noqa: E402
from suspensionlab.core.cad_tube_envelope import build_tube_envelope  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.fixed_arm_housings import make_housing_preview  # noqa: E402
from suspensionlab.model.fixed_arm_skeleton import (  # noqa: E402
    capture_fixed_arm,
    fixed_arm_tube_document,
    preview_fixed_arm,
)
from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft  # noqa: E402
from suspensionlab.model.free_arm_inner_housings import FreeArmInnerHousings  # noqa: E402
from suspensionlab.model.free_arm_tube_joint import FreeArmTubeJoint, FreeArmTubeJointDraft  # noqa: E402
from suspensionlab.model.free_arm_tube_joint_io import to_data  # noqa: E402
from suspensionlab.model.templates import load_template  # noqa: E402


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1e-8)
    return abs(float(props.Mass()))


def children(shape):
    it, result = TopoDS_Iterator(shape), []
    while it.More():
        result.append(it.Value())
        it.Next()
    return result


@pytest.mark.parametrize(('target', 'bent', 'inner'), [
    ('front', (), False), ('rear', (), False), ('front', ('rear',), False),
    ('rear', ('front',), False), ('front', ('front',), True), ('rear', ('rear',), True),
])
def test_same_results_as_snapshot_for_explicit_points(target, bent, inner):
    project = load_template('ring')
    before = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20)
    points = preview_fixed_arm(snapshot, project, 10, 2).anchors
    bends = {}
    for index, leg in enumerate(('front', 'rear')):
        if leg in bent:
            vertex = [(points[index][i] + points[2][i]) / 2 for i in range(3)]
            vertex[2] += 50
            bends[leg] = {'vertex_mm': vertex, 'radius_mm': 20}
    arm = FreeArmDraft(*points, 10, 2, *(FreeArmBend(bends[leg]['vertex_mm'], 20) if leg in bends else None
                                        for leg in ('front', 'rear')))
    inner_model = FreeArmInnerHousings.from_data(housings(), {'rear': 1}) if inner else None
    draft = FreeArmTubeJointDraft(arm, FreeArmTubeJoint(target, .5), inner_model)
    _, actual = build_free_arm_tube_joint(draft)
    snapshot_tubes = fixed_arm_tube_document(snapshot, project, 10, 2, bends)
    expected = children(build_fixed_arm_housing_preview(make_housing_preview(
        snapshot_tubes, housings() if inner else None, {'rear': 1} if inner else None,
        {'target': target, 'radial_clearance_mm': .5})))
    assert len(actual) == len(expected) == (4 if inner else 2)
    for a, b in zip(actual, expected, strict=True):
        assert BRepCheck_Analyzer(a).IsValid()
        assert volume(a) == pytest.approx(volume(b), rel=1e-7)
        for one, other in ((a, b), (b, a)):
            cut = BRepAlgoAPI_Cut(one, other)
            assert cut.IsDone() and volume(cut.Shape()) < 1e-5
    index = ('front', 'rear').index(target)
    opposite = 1 - index
    cutter = build_tube_envelope(_free_arm_geometries(arm)[opposite], points[opposite], points[2], .5)
    common = BRepAlgoAPI_Common(actual[index], cutter)
    assert common.IsDone() and volume(common.Shape()) < 1e-5
    if not inner:
        _, originals = build_free_arm_tubes(arm)
        assert volume(actual[opposite]) == pytest.approx(volume(originals[opposite]), rel=1e-8)
        assert volume(actual[index]) < volume(originals[index])
    mesh = WeldmentCadJob().run(to_data(draft))
    assert mesh.part_names == (('tube_front', 'tube_rear', 'housing_front', 'housing_rear') if inner else
                               ('tube_front', 'tube_rear'))
    assert mesh.all_parts_present() and project.to_dict() == before


def test_invalid_enlarged_bend_reports_selected_joint():
    arm = make_draft(('front',)).arm
    bad = FreeArmTubeJointDraft(arm, FreeArmTubeJoint('rear', 30))
    with pytest.raises(CadPreviewError) as error:
        WeldmentCadJob().run(to_data(bad))
    assert error.value.code == 'tube_joint_rear_failed'


def test_worker_preserves_memory_and_inner_notch_errors(monkeypatch, tmp_path):
    from suspensionlab.core import cad_free_arm
    from suspensionlab.core.cad_kim_prototype import FixedArmNotchError
    from suspensionlab.core.cad_weldment_worker import create_grouped_mesh
    from suspensionlab.core.cad_worker import CadWorkerError
    from suspensionlab.model.free_arm_tube_joint_io import write_free_arm_tube_joint

    draft = FreeArmTubeJointDraft(make_draft().arm, FreeArmTubeJoint('front', 0))
    path = write_free_arm_tube_joint(tmp_path / 'joint.slarm', draft)
    for problem, expected in ((MemoryError('test'), 'memory'),
                              (FixedArmNotchError('rear', 'no_overlap'), 'notch_rear_no_overlap'),
                              (FixedArmNotchError('front', 'empty_or_split', tube_joint=True),
                               'tube_joint_front_empty_or_split')):
        def fail(_draft, exception=problem):
            raise exception
        monkeypatch.setattr(cad_free_arm, 'build_free_arm_tube_joint', fail)
        with pytest.raises(CadWorkerError) as error:
            create_grouped_mesh(path, 2.)
        assert error.value.code == expected
