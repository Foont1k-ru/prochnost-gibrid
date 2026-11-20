"""Аналитические пары и реальные тела в изолированном CAD-процессе."""
from copy import deepcopy

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRep import BRep_Builder  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCP.gp import gp_Pnt  # noqa: E402
from OCP.TopoDS import TopoDS_Compound  # noqa: E402
from test_fixed_arm_housings import housings  # noqa: E402

from suspensionlab.core import cad_fixed_arm_overlap as overlap  # noqa: E402
from suspensionlab.core.cad_fixed_arm_overlap_job import FixedArmOverlapJob  # noqa: E402
from suspensionlab.model.fixed_arm_housings import PREVIEW_FORMAT, make_housing_preview  # noqa: E402
from suspensionlab.model.fixed_arm_skeleton import (  # noqa: E402
    capture_fixed_arm,
    fixed_arm_tube_document,
    preview_fixed_arm,
)
from suspensionlab.model.templates import load_template  # noqa: E402


def test_six_pairs_known_cube_intersections_touch_and_separation(monkeypatch):
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for x in (0.0, 0.5, 1.0, 3.0):
        builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(x, 0, 0), 1, 1, 1).Shape())
    monkeypatch.setattr(overlap, 'validate_housing_preview', lambda doc: None)
    monkeypatch.setattr(overlap, 'build_fixed_arm_housing_preview', lambda doc: compound)
    doc = {'format': PREVIEW_FORMAT, 'housings': {}}
    result = overlap.measure_all_pairs(doc)
    assert [(row['left'], row['right']) for row in result] == [
        ('tube_front', 'tube_rear'), ('tube_front', 'housing_front'), ('tube_front', 'housing_rear'),
        ('tube_rear', 'housing_front'), ('tube_rear', 'housing_rear'), ('housing_front', 'housing_rear')]
    assert [row['overlap_mm3'] for row in result] == pytest.approx([0.5, 0, 0, 0.5, 0, 0])
    assert all(row['threshold_mm3'] > 0 for row in result)


def test_any_invalid_pair_fails_whole_result(monkeypatch):
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for x in (0.0, 0.5, 1.0, 3.0):
        builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(x, 0, 0), 1, 1, 1).Shape())
    monkeypatch.setattr(overlap, 'validate_housing_preview', lambda doc: None)
    monkeypatch.setattr(overlap, 'build_fixed_arm_housing_preview', lambda doc: compound)
    initial = overlap._measure_pair
    calls = []
    def fail_on_fourth(*args):
        calls.append(1)
        if len(calls) == 4:
            raise ValueError('intersection_failed')
        return initial(*args)
    monkeypatch.setattr(overlap, '_measure_pair', fail_on_fourth)
    with pytest.raises(ValueError, match='intersection_failed'):
        overlap.measure_all_pairs({'format': PREVIEW_FORMAT, 'housings': {}})
    assert len(calls) == 4


def test_invalid_boolean_result_is_rejected(monkeypatch):
    import OCP.BRepCheck as BRepCheck

    cube = BRepPrimAPI_MakeBox(1, 1, 1).Shape()
    class InvalidAnalyzer:
        def __init__(self, shape):
            pass

        def IsValid(self):  # noqa: N802 — API OCCT
            return False

    monkeypatch.setattr(BRepCheck, 'BRepCheck_Analyzer', InvalidAnalyzer)
    with pytest.raises(ValueError, match='intersection_failed'):
        overlap._measure_pair(cube, cube, 1, 1)


@pytest.mark.parametrize('joint', [False, True])
def test_four_body_worker_and_two_body_worker_are_consistent(joint):
    project = load_template('ring')
    original = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    vertex = [(anchors[0][i] + anchors[2][i]) / 2 for i in range(3)]
    vertex[2] += 50
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2,
                                    {'front': {'vertex_mm': vertex, 'radius_mm': 20}})
    joint_data = {'target': 'rear', 'radial_clearance_mm': 0.5} if joint else None
    four = make_housing_preview(tubes, housings(), {'front': 0.5}, joint_data)
    for doc, expected_count in [(tubes, 1), (four, 6)]:
        direct = overlap.measure_all_pairs(doc)
        report = FixedArmOverlapJob().run_all(doc)
        assert len(report.pairs) == expected_count
        for pair, expected in zip(report.pairs, direct, strict=True):
            assert (pair.left, pair.right) == (expected['left'], expected['right'])
            assert pair.overlap_mm3 == pytest.approx(expected['overlap_mm3'], abs=1e-6, rel=1e-7)
            assert pair.threshold_mm3 == pytest.approx(expected['threshold_mm3'], rel=1e-8)
        assert report.pairs[0].overlap_mm3 == pytest.approx(overlap.measure_overlap(doc)['overlap_mm3'], abs=1e-6)
    if joint:
        two = make_housing_preview(tubes, None, tube_joint=joint_data)
        report = FixedArmOverlapJob().run_all(two)
        assert len(report.pairs) == 1 and report.pairs[0].overlap_mm3 <= report.pairs[0].threshold_mm3
    assert project.to_dict() == original
