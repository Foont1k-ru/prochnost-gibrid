"""CAD-дистанции на известных телах и снимках с подрезками."""
from copy import deepcopy

import pytest

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
from OCP.BRep import BRep_Builder  # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCP.gp import gp_Pnt  # noqa: E402
from OCP.TopoDS import TopoDS_Compound  # noqa: E402
from test_fixed_arm_housings import housings  # noqa: E402

from suspensionlab.core import cad_fixed_arm_overlap as core  # noqa: E402
from suspensionlab.core.cad_fixed_arm_overlap_job import FixedArmOverlapJob, _parse_proximity  # noqa: E402
from suspensionlab.model.fixed_arm_housings import make_housing_preview  # noqa: E402
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, fixed_arm_tube_document  # noqa: E402
from suspensionlab.model.templates import load_template  # noqa: E402


def compound_of(*shapes):
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    return compound


def cube(x, size=1):
    return BRepPrimAPI_MakeBox(gp_Pnt(x, 0, 0), size, size, size).Shape()


@pytest.mark.parametrize(('offset', 'status', 'distance', 'volume'), [
    (0.5, 'intersection', 0, 0.5), (1, 'near', 0, 0),
    (1.000005, 'near', 0.000005, 0), (1.25, 'gap', 0.25, 0),
])
def test_analytic_boxes(monkeypatch, offset, status, distance, volume):
    monkeypatch.setattr(core, 'weldment_source_matches', lambda doc: True)
    monkeypatch.setattr(core, 'build_weldment_tubes_preview', lambda doc: compound_of(cube(0), cube(offset)))
    doc = {'format': 'kima-assembly'}
    values = core.measure_proximity(doc)
    pair = _parse_proximity(values, doc).pairs[0]
    assert pair.status == status
    assert pair.distance_mm == pytest.approx(distance, abs=1e-7)
    assert pair.overlap_mm3 == pytest.approx(volume, abs=1e-8)


def test_complete_containment_is_intersection_not_positive_surface_gap(monkeypatch):
    outer = BRepPrimAPI_MakeBox(5, 5, 5).Shape()
    inner = BRepPrimAPI_MakeBox(gp_Pnt(2, 2, 2), 1, 1, 1).Shape()
    monkeypatch.setattr(core, 'weldment_source_matches', lambda doc: True)
    monkeypatch.setattr(core, 'build_weldment_tubes_preview', lambda doc: compound_of(outer, inner))
    doc = {'format': 'kima-assembly'}
    pair = _parse_proximity(core.measure_proximity(doc), doc).pairs[0]
    assert pair.status == 'intersection' and pair.distance_mm == pytest.approx(0)
    assert pair.overlap_mm3 == pytest.approx(1)


def test_failed_pair_is_explicit_other_pairs_are_measured(monkeypatch):
    from suspensionlab.model.fixed_arm_housings import PREVIEW_FORMAT

    monkeypatch.setattr(core, 'validate_housing_preview', lambda doc: None)
    monkeypatch.setattr(core, 'build_fixed_arm_housing_preview', lambda doc: compound_of(*(cube(x) for x in (0, 2, 4, 6))))
    original = core._distance
    calls = []
    def fail_once(*args):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError('distance_failed')
        return original(*args)
    monkeypatch.setattr(core, '_distance', fail_once)
    doc = {'format': PREVIEW_FORMAT, 'housings': {}}
    report = _parse_proximity(core.measure_proximity(doc), doc)
    assert [pair.status for pair in report.pairs] == ['gap', 'error', 'gap', 'gap', 'gap', 'gap']
    assert report.pairs[1].distance_mm is None


@pytest.mark.parametrize('with_housings', [False, True])
def test_subprocess_rebuilds_selected_notches_without_changing_project(with_housings):
    project = load_template('ring')
    before = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20)
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2)
    joint = {'target': 'rear', 'radial_clearance_mm': 0.5}
    doc = make_housing_preview(tubes, housings() if with_housings else None,
                               {'front': 0.5} if with_housings else None, joint)
    direct = _parse_proximity(core.measure_proximity(doc), doc)
    subprocess_result = FixedArmOverlapJob().run_proximity(doc)
    untrimmed = _parse_proximity(core.measure_proximity(tubes), tubes)
    assert untrimmed.pairs[0].status == 'intersection'
    assert subprocess_result.pairs[0].status in ('near', 'uncertain_overlap', 'gap')
    assert len(subprocess_result.pairs) == (6 if with_housings else 1)
    for a, b in zip(direct.pairs, subprocess_result.pairs, strict=True):
        assert a.status == b.status != 'error'
        assert a.distance_mm == pytest.approx(b.distance_mm, abs=1e-7)
        assert a.overlap_mm3 == pytest.approx(b.overlap_mm3, abs=1e-6)
    assert subprocess_result.pairs[0].overlap_mm3 <= subprocess_result.pairs[0].threshold_mm3
    assert project.to_dict() == before
