from pathlib import Path

import pytest

from suspensionlab.core import step_inventory as step


def fixture_step() -> bytes:
    return (r"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('quoted; value'),'2;1');
FILE_SCHEMA(('AP242'));
ENDSEC;
DATA;
/* ; #999=PRODUCT('fake','fake'); */
#1=PRODUCT('main','Assembly', '',());
#2=PRODUCT('part','\X2\0420044B044704300433\X0\; ''A''','',());
#3=PRODUCT_DEFINITION_FORMATION('','',#1);
#4=PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#2,.NOT_KNOWN.);
#5=PRODUCT_DEFINITION('','',#3,#100);
#6=PRODUCT_DEFINITION('','',#4,#100);
#7=NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','first','',#5,#6,$);
#8=NEXT_ASSEMBLY_USAGE_OCCURRENCE('2','second','',#5,#6,$);
#9=NEXT_ASSEMBLY_USAGE_OCCURRENCE('3','missing','',#5,#998,$);
#10=MANIFOLD_SOLID_BREP('',#11);
#11=ITEM_DEFINED_TRANSFORMATION('','',#12,#13);
#12=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));
ENDSEC;
END-ISO-10303-21;
""").encode("ascii")


def test_inventory_joins_definitions_without_confusing_occurrences(tmp_path: Path):
    path = tmp_path / "пример.stp"
    raw = fixture_step()
    path.write_bytes(raw)
    result = step.read_step_inventory(path)
    assert path.read_bytes() == raw
    assert result.schema == ("AP242",)
    assert len(result.products) == 2 and result.definitions == 2
    assert result.products[1].name == "Рычаг; 'A'"
    assert len(result.occurrences) == 3
    assert result.occurrences[0].parent == result.products[0]
    assert result.occurrences[0].child == result.products[1]
    assert result.occurrences[1].child == result.products[1]
    assert result.occurrences[2].child is None and result.unresolved_occurrences == 1
    assert result.solid_records == 1 and result.transformation_records == 1
    assert not result.non_ascii_bytes and not result.unsupported_string_escape


def test_unicode_and_unsupported_encodings(tmp_path: Path):
    path = tmp_path / "part.stp"
    path.write_bytes(fixture_step().replace(b"Assembly", b"\\X4\\0001F680\\X0\\"))
    assert step.read_step_inventory(path).products[0].name == "🚀"
    path.write_bytes(fixture_step().replace(b"Assembly", b"\\S\\a\xff"))
    result = step.read_step_inventory(path)
    assert result.unsupported_string_escape and result.non_ascii_bytes


@pytest.mark.parametrize("change", [
    lambda text: text.replace(b"END-ISO-10303-21;", b""),
    lambda text: text.replace(b"#2=PRODUCT", b"#1=PRODUCT"),
    lambda text: text.replace(b"#2=PRODUCT", b"#0=PRODUCT"),
    lambda text: text.replace(b"#5,#6,$", b"#5,$,$"),
    lambda text: text.replace(b"'first'", b"'unclosed"),
    lambda text: text.replace(b"0420044B044704300433", b"0420044B04470430043"),
    lambda text: text.replace(b"DATA;", b"DATA('unsupported');"),
    lambda text: text.replace(b"END-ISO-10303-21;", b"DATA;ENDSEC;END-ISO-10303-21;"),
])
def test_rejects_bad_or_unsupported_files(tmp_path: Path, change):
    path = tmp_path / "bad.step"
    path.write_bytes(change(fixture_step()))
    with pytest.raises(step.StepInventoryError):
        step.read_step_inventory(path)


def test_limits_and_io_fail_cleanly(tmp_path: Path, monkeypatch):
    path = tmp_path / "large.stp"
    path.write_bytes(fixture_step())
    monkeypatch.setattr(step, "MAX_BYTES", 20)
    with pytest.raises(step.StepInventoryError, match="64"):
        step.read_step_inventory(path)
    with pytest.raises(step.StepInventoryError, match="прочитать"):
        step.read_step_inventory(tmp_path / "missing")
