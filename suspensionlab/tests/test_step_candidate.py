"""Ограниченные кандидаты нельзя использовать как проверенные положения."""
from dataclasses import replace
from pathlib import Path

import pytest

from suspensionlab.core.step_candidate import candidate_transforms
from suspensionlab.core.step_inventory import read_step_inventory


def sample(tmp_path: Path, prefix: str = ".MILLI."):
    data = f"""ISO-10303-21;HEADER;FILE_SCHEMA(('AP242'));ENDSEC;DATA;
#1=PRODUCT('','parent','',());#2=PRODUCT('','child','',());
#3=PRODUCT_DEFINITION_FORMATION('','',#1);#4=PRODUCT_DEFINITION_FORMATION('','',#2);
#5=PRODUCT_DEFINITION('','',#3,#100);#6=PRODUCT_DEFINITION('','',#4,#100);
#7=NEXT_ASSEMBLY_USAGE_OCCURRENCE('','part','',#5,#6,$);
#20=PRODUCT_DEFINITION_SHAPE('','',#7);#21=CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#22,#20);
#22=(REPRESENTATION_RELATIONSHIP('','',#100,#101)REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#23)SHAPE_REPRESENTATION_RELATIONSHIP());
#23=ITEM_DEFINED_TRANSFORMATION('','',#30,#31);
#30=AXIS2_PLACEMENT_3D('',#32,$,$);#31=AXIS2_PLACEMENT_3D('',#33,#34,#35);
#32=CARTESIAN_POINT('',(1.,2.,3.));#33=CARTESIAN_POINT('',(10.,20.,30.));
#34=DIRECTION('',(0.,0.,1.));#35=DIRECTION('',(0.,1.,0.));
#40=PRODUCT_DEFINITION_SHAPE('','',#6);#41=SHAPE_DEFINITION_REPRESENTATION(#40,#100);
#42=PRODUCT_DEFINITION_SHAPE('','',#5);#43=SHAPE_DEFINITION_REPRESENTATION(#42,#101);
#100=SHAPE_REPRESENTATION('',(#30),#200);#101=SHAPE_REPRESENTATION('',(#30,#31),#200);
#200=(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNIT_ASSIGNED_CONTEXT((#201))REPRESENTATION_CONTEXT('',''));
#201=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT({prefix},.METRE.));
ENDSEC;END-ISO-10303-21;""".encode("ascii")
    path = tmp_path / "sample.stp"
    path.write_bytes(data)
    return read_step_inventory(path)


def test_candidate_has_expected_active_alignment_and_unit_conversion(tmp_path):
    result = sample(tmp_path)
    candidate, = candidate_transforms(result)
    assert candidate.status == "ready" and candidate.transform is not None
    assert candidate.transform.apply_point((1, 2, 3)) == pytest.approx((10, 20, 30))
    assert candidate.transform.apply_direction((1, 0, 0)) == pytest.approx((0, 1, 0))
    assert candidate.transform.translation == pytest.approx((12, 19, 27))
    metres = sample(tmp_path, "$")
    candidate, = candidate_transforms(metres)
    assert candidate.status == "ready" and candidate.transform is not None
    assert candidate.transform.translation == pytest.approx((12000, 19000, 27000))
    assert metres.placement_frames[0].second.origin == (10, 20, 30)


def test_no_implicit_guess_for_missing_or_ambiguous_data(tmp_path):
    result = sample(tmp_path)
    frame = result.placement_frames[0]
    occurrence = result.occurrences[0]
    info = frame.representation_match
    assert info and frame.first
    alternatives = [
        (replace(result, placement_frames=()), "frames"),
        (replace(result, placement_frames=(replace(frame, issue="invalid"),)), "frames"),
        (replace(result, occurrences=(replace(occurrence, child=None),)), "definitions"),
        (replace(result, placement_frames=(replace(frame, representation_match=replace(info, status="parent_child")),)), "association"),
        (replace(result, placement_frames=(replace(frame, representation_match=replace(info, status="ambiguous")),)), "association"),
        (replace(result, placement_frames=(replace(frame, representation_match=replace(info, frame_1_membership=(None, True))),)), "membership"),
        (replace(result, placement_frames=(replace(frame, representation_match=replace(info, frame_2_membership=(True, False))),)), "membership"),
        (replace(result, placement_frames=(replace(frame, representation_match=replace(info, context_2=201)),)), "context"),
        (replace(result, context_units=()), "unit"),
        (replace(result, context_units=(replace(result.context_units[0], status="ambiguous", mm_per_unit=None),)), "unit"),
        (replace(result, context_units=(replace(result.context_units[0], mm_per_unit=float("nan")),)), "unit"),
        (replace(result, placement_frames=(replace(frame, first=replace(frame.first, origin=(float("inf"), 0, 0))),)), "invalid"),
    ]
    for modified, expected in alternatives:
        candidate, = candidate_transforms(modified)
        assert candidate.status == expected and candidate.transform is None
