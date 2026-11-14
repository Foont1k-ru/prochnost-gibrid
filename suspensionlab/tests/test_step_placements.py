from pathlib import Path

import pytest

from suspensionlab.core import step_placements as placements
from suspensionlab.core.step_inventory import read_step_inventory


def step_file(extra: str) -> bytes:
    return f"""ISO-10303-21;HEADER;FILE_SCHEMA(('AP242'));ENDSEC;DATA;
#1=PRODUCT('P','Parent','',());
#2=PRODUCT('C','Child','',());
#3=PRODUCT_DEFINITION_FORMATION('','',#1);
#4=PRODUCT_DEFINITION_FORMATION('','',#2);
#5=PRODUCT_DEFINITION('','',#3,#100);
#6=PRODUCT_DEFINITION('','',#4,#100);
#7=NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','first','',#5,#6,$);
#8=NEXT_ASSEMBLY_USAGE_OCCURRENCE('2','second','',#5,#6,$);
#20=PRODUCT_DEFINITION_SHAPE('','',#7);
#21=CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#22,#20);
#22=(REPRESENTATION_RELATIONSHIP('','',#100,#101)
REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#23)SHAPE_REPRESENTATION_RELATIONSHIP());
#23=ITEM_DEFINED_TRANSFORMATION('','',#30,#31);
#30=AXIS2_PLACEMENT_3D('',#32,#33,#34);
#31=AXIS2_PLACEMENT_3D('',#35,$,$);
#32=CARTESIAN_POINT('',(1.,2.,3.));
#33=DIRECTION('',(0.,0.,2.));
#34=DIRECTION('',(1.,1.,4.));
#35=CARTESIAN_POINT('',(-5.,0.,9.));
{extra}
ENDSEC;END-ISO-10303-21;""".encode("ascii")


def read(tmp_path: Path, data: bytes):
    path = tmp_path / "sample.stp"
    path.write_bytes(data)
    return read_step_inventory(path)


def test_frame_chain_orthonormal_basis_and_missing_occurrence(tmp_path):
    result = read(tmp_path, step_file(""))
    found, missing = result.placement_frames
    assert (found.occurrence, found.relation, found.transformation, found.issue) == (7, 22, 23, None)
    assert found.first and found.second
    assert found.first.origin == pytest.approx((1, 2, 3))
    assert found.first.z == pytest.approx((0, 0, 1))
    assert found.first.x == pytest.approx((2**-0.5, 2**-0.5, 0))
    assert found.first.y == pytest.approx((-2**-0.5, 2**-0.5, 0))
    assert found.second.origin == pytest.approx((-5, 0, 9))
    assert found.second.x == pytest.approx((1, 0, 0))
    assert found.second.y == pytest.approx((0, 1, 0))
    assert found.second.z == pytest.approx((0, 0, 1))
    assert missing.occurrence == 8 and missing.issue == "missing" and missing.first is None


@pytest.mark.parametrize("old,new", [
    (b"(0.,0.,2.)", b"(0.,0.,0.)"),
    (b"(1.,1.,4.)", b"(0.,0.,3.)"),
    (b"(1.,1.,4.)", b"(0.,0.,1.,0.)"),
    (b"(1.,1.,4.)", b"(1.E999,0.,0.)"),
    (b"#35,$,$", b"#35,#33,$"),
    (b"#32=CARTESIAN_POINT", b"#32=DIRECTION"),
    (b"#35=CARTESIAN_POINT", b"#35=OTHER_POINT"),
    (b"#30=AXIS2_PLACEMENT_3D", b"#30=AXIS2_PLACEMENT_2D"),
])
def test_invalid_or_unhandled_frames_are_never_fabricated(tmp_path, old, new):
    found = read(tmp_path, step_file("").replace(old, new)).placement_frames[0]
    assert found.issue == "invalid" and found.first is None and found.second is None


def test_ambiguous_or_unsupported_links_are_not_guessed(tmp_path):
    duplicate = read(tmp_path, step_file("#40=CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#22,#20);"))
    assert duplicate.placement_frames[0].issue == "ambiguous"
    unsupported = read(tmp_path, step_file("").replace(b"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#23)", b"SOME_OTHER_TRANSFORM(#23)"))
    assert unsupported.placement_frames[0].issue == "unsupported"
    missing = read(tmp_path, step_file("").replace(b"#23=ITEM_DEFINED_TRANSFORMATION", b"#23=OTHER_TRANSFORMATION"))
    assert missing.placement_frames[0].issue == "unsupported"


def test_transform_component_is_not_guessed_from_quoted_or_nested_text(tmp_path):
    original = b"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#23)"
    for substitute in (b"OTHER('REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#23)')",
                       b"OTHER(REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#23))"):
        result = read(tmp_path, step_file("").replace(original, substitute))
        assert result.placement_frames[0].issue == "unsupported"
    duplicate = step_file("").replace(original, original + original)
    assert read(tmp_path, duplicate).placement_frames[0].issue == "ambiguous"


def test_limit_does_not_destroy_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(placements, "_LIMIT", 0)
    result = read(tmp_path, step_file(""))
    assert len(result.products) == 2 and len(result.occurrences) == 2
    assert result.placement_limit and result.placement_frames == ()
