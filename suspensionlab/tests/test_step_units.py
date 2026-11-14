from pathlib import Path

import pytest

from suspensionlab.core.step_inventory import read_step_inventory
from suspensionlab.core.step_units import inspect_context_units


def step(*records: str) -> str:
    return "ISO-10303-21;HEADER;ENDSEC;DATA;" + ";".join(records) + ";ENDSEC;END-ISO-10303-21;"


def context(refs: str) -> str:
    return f"#10=(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNIT_ASSIGNED_CONTEXT(({refs}))REPRESENTATION_CONTEXT('',''))"


def length(prefix: str = ".MILLI.") -> str:
    return f"#11=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT({prefix},.METRE.))"


ANGLE = "#12=(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))"
SOLID_ANGLE = "#13=(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())"


@pytest.mark.parametrize(("prefix", "expected"), [("$", 1000), (".KILO.", 1_000_000), (".CENTI.", 10),
                                                   (".MILLI.", 1), (".MICRO.", 0.001), (".NANO.", 0.000001)])
def test_direct_si_prefixes_have_independent_known_scale(prefix, expected):
    text = step(context("#11,#12,#13"), length(prefix), ANGLE, SOLID_ANGLE)
    result, = inspect_context_units(text, {10})
    assert result.status == "known" and result.unit_entity == 11
    assert result.mm_per_unit == pytest.approx(expected)


def test_distinct_contexts_are_not_assumed_equal():
    text = step(context("#11"), length(),
                "#20=(GLOBAL_UNIT_ASSIGNED_CONTEXT((#21))REPRESENTATION_CONTEXT('',''))",
                "#21=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT($,.METRE.))")
    first, second = inspect_context_units(text, {10, 20})
    assert first.mm_per_unit == 1 and second.mm_per_unit == 1000
    assert first.unit_entity != second.unit_entity


@pytest.mark.parametrize(("records", "status"), [
    (["#10=(REPRESENTATION_CONTEXT('',''))"], "missing"),
    (["#10=GEOMETRIC_REPRESENTATION_CONTEXT(3)"], "missing"),
    ([context("#404")], "unsupported"),
    ([context("#11,#404"), length()], "unsupported"),
    ([context("#11,#11"), length()], "ambiguous"),
    ([context("#11,#14"), length(), "#14=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT($,.METRE.))"], "ambiguous"),
    ([context("#11"), "#11=(CONVERSION_BASED_UNIT('INCH',#55)LENGTH_UNIT()NAMED_UNIT(#56))"], "unsupported"),
    ([context("#11"), length(".INVALID.")], "unsupported"),
    ([context("#11"), "#11=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT($,.SECOND.))"], "unsupported"),
    ([context("#11"), "#11=(LENGTH_UNIT()NAMED_UNIT(#88)SI_UNIT($,.METRE.))"], "unsupported"),
    ([context("#11"), "#11=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT($,.METRE.)MASS_UNIT())"], "unsupported"),
    ([context("#12"), ANGLE], "unsupported"),
    (["#10=(GLOBAL_UNIT_ASSIGNED_CONTEXT((#11))GLOBAL_UNIT_ASSIGNED_CONTEXT((#11))REPRESENTATION_CONTEXT('',''))", length()], "ambiguous"),
    (["#10=(OTHER('GLOBAL_UNIT_ASSIGNED_CONTEXT((#11))')REPRESENTATION_CONTEXT('',''))", length()], "missing"),
    (["#10=(OTHER(GLOBAL_UNIT_ASSIGNED_CONTEXT((#11)))REPRESENTATION_CONTEXT('',''))", length()], "missing"),
])
def test_non_si_missing_or_conflicting_never_yield_scale(records, status):
    result, = inspect_context_units(step(*records), {10})
    assert result.status == status and result.mm_per_unit is None and result.unit_entity is None


def test_missing_context_and_empty_selection():
    assert inspect_context_units(step("#1=PRODUCT('','','',())"), set()) == ()
    missing, = inspect_context_units(step("#1=PRODUCT('','','',())"), {10})
    assert missing.status == "missing"


def test_global_unit_reference_limit_reports_unknown(monkeypatch):
    from suspensionlab.core import step_units

    monkeypatch.setattr(step_units, "_MAX_TOTAL_REFERENCES", 1)
    results = inspect_context_units(step(context("#11,#12"), length(), ANGLE), {10})
    assert results[0].status == "limit" and results[0].mm_per_unit is None


def test_inventory_context_unit_is_diagnostic_only(tmp_path: Path):
    data = step(
        "#1=PRODUCT('','parent','',())", "#2=PRODUCT('','child','',())",
        "#3=PRODUCT_DEFINITION_FORMATION('','',#1)", "#4=PRODUCT_DEFINITION_FORMATION('','',#2)",
        "#5=PRODUCT_DEFINITION('','',#3,#100)", "#6=PRODUCT_DEFINITION('','',#4,#100)",
        "#7=NEXT_ASSEMBLY_USAGE_OCCURRENCE('','','',#5,#6,$)",
        "#20=PRODUCT_DEFINITION_SHAPE('','',#7)", "#21=CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#22,#20)",
        "#22=(REPRESENTATION_RELATIONSHIP('','',#80,#81)REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#23)SHAPE_REPRESENTATION_RELATIONSHIP())",
        "#23=ITEM_DEFINED_TRANSFORMATION('','',#30,#31)",
        "#30=AXIS2_PLACEMENT_3D('',#32,$,$)", "#31=AXIS2_PLACEMENT_3D('',#33,$,$)",
        "#32=CARTESIAN_POINT('',(0.,0.,0.))", "#33=CARTESIAN_POINT('',(1.,2.,3.))",
        "#80=SHAPE_REPRESENTATION('',(#30),#10)", "#81=SHAPE_REPRESENTATION('',(#30,#31),#10)",
        context("#11,#12"), length("$"), ANGLE,
    ).encode("ascii")
    path = tmp_path / "sample.stp"
    path.write_bytes(data)
    result = read_step_inventory(path)
    assert path.read_bytes() == data
    assert len(result.context_units) == 1 and result.context_units[0].mm_per_unit == 1000
    assert result.placement_frames[0].second.origin == (1, 2, 3)  # no conversion
