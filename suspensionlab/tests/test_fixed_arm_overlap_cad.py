"""CAD-анализ двух труб не выдает заключения о касании или зазоре."""
from copy import deepcopy

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRep import BRep_Builder  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCP.gp import gp_Pnt  # noqa: E402
from OCP.TopoDS import TopoDS_Compound  # noqa: E402
from test_fixed_arm_housings import housings  # noqa: E402

from suspensionlab.core import cad_fixed_arm_overlap as overlap  # noqa: E402
from suspensionlab.core.cad_fixed_arm_overlap_job import FixedArmOverlapJob, OverlapJobError  # noqa: E402
from suspensionlab.model.fixed_arm_housings import make_housing_preview  # noqa: E402
from suspensionlab.model.fixed_arm_skeleton import (  # noqa: E402
    capture_fixed_arm,
    fixed_arm_tube_document,
    preview_fixed_arm,
)
from suspensionlab.model.templates import load_template  # noqa: E402


@pytest.mark.parametrize('bent', [False, True])
def test_real_overlap_process_with_straight_and_bent_tubes(bent):
    project = load_template('ring')
    original = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    vertex = [(anchors[0][i] + anchors[2][i]) / 2 for i in range(3)]
    vertex[2] += 50
    bends = {'front': {'vertex_mm': vertex, 'radius_mm': 20}} if bent else {}
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2, bends)
    for doc in (tubes, make_housing_preview(tubes, housings(), {'front': 0.5})):
        direct = overlap.measure_overlap(doc)
        result = FixedArmOverlapJob().run(doc)
        assert result.overlap_mm3 == pytest.approx(direct['overlap_mm3'], rel=1e-8, abs=1e-8)
        assert result.threshold_mm3 == pytest.approx(direct['threshold_mm3'], rel=1e-8)
        assert result.overlap_mm3 > result.threshold_mm3 > 0
    assert project.to_dict() == original


@pytest.mark.parametrize(('offset', 'expected'), [(0.5, 0.5), (1.0, 0.0), (2.0, 0.0)])
def test_known_intersection_volume_and_touching_does_not_prove_gap(monkeypatch, offset, expected):
    # Two 1 mm cubes: overlap 0.5 mm³, face contact, and separation.
    # Both zero-volume cases must remain indistinguishable as to clearance.
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 1, 1, 1).Shape())
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(offset, 0, 0), 1, 1, 1).Shape())
    monkeypatch.setattr(overlap, 'weldment_source_matches', lambda doc: True)
    monkeypatch.setattr(overlap, 'build_weldment_tubes_preview', lambda doc: compound)
    result = overlap.measure_overlap({'format': 'kima-assembly'})
    assert result['overlap_mm3'] == pytest.approx(expected) and result['threshold_mm3'] > 0


def test_cancel_and_stale_document_are_rejected():
    job = FixedArmOverlapJob()
    job.cancel()
    with pytest.raises(OverlapJobError, match='cancelled'):
        job.run({})
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    doc = fixed_arm_tube_document(snapshot, project, 10, 2)
    doc['parts'][0]['geometry']['source']['coordinates_mm'][0][0] += 10
    with pytest.raises(OverlapJobError, match='invalid'):
        FixedArmOverlapJob().run(doc)
