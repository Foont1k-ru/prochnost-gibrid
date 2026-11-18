"""Проверки разбора и форматирования величин (ввод значений и единиц)."""

from __future__ import annotations

import pytest

from suspensionlab.model.units import (
    UnitConversionError,
    UnitKind,
    UnitSettings,
    eval_expression,
    format_angle_deg_min,
    format_number,
    parse_length_mm,
)


def test_parse_plain_and_decimal_comma() -> None:
    assert parse_length_mm("342.5") == pytest.approx(342.5)
    assert parse_length_mm("342,5") == pytest.approx(342.5)


def test_parse_thousands_separator() -> None:
    assert parse_length_mm("1 234,5") == pytest.approx(1234.5)
    assert parse_length_mm("1,234.5") == pytest.approx(1234.5)


def test_parse_units_in_text() -> None:
    assert parse_length_mm('1"') == pytest.approx(25.4)
    assert parse_length_mm("2.5in") == pytest.approx(63.5)
    assert parse_length_mm("12 см") == pytest.approx(120.0)
    assert parse_length_mm("340 мм") == pytest.approx(340.0)


def test_parse_expression() -> None:
    assert parse_length_mm("120+15/2") == pytest.approx(127.5)
    assert parse_length_mm("340*0.98") == pytest.approx(333.2)
    assert eval_expression("(10+5)*2") == pytest.approx(30.0)


def test_division_by_zero_is_reported() -> None:
    with pytest.raises(UnitConversionError) as error:
        parse_length_mm("10/0")
    assert error.value.message_key == "error.number.division_by_zero"


def test_bad_input_is_reported() -> None:
    with pytest.raises(UnitConversionError) as error:
        parse_length_mm("abc")
    assert error.value.message_key == "error.number.format"


def test_angle_degrees_minutes() -> None:
    settings = UnitSettings(angle="degmin")
    assert settings.parse('-12°30′', UnitKind.ANGLE) == pytest.approx(-12.5)
    assert format_angle_deg_min(-12.5) == "-12°30′"
    assert settings.display(1.0, UnitKind.ANGLE) == "1°00′"


def test_display_respects_units() -> None:
    mm = UnitSettings(length="mm")
    inches = UnitSettings(length="in")
    assert mm.display(25.4, UnitKind.LENGTH) == "25,4"
    assert inches.display(25.4, UnitKind.LENGTH) == "1,0"


def test_format_number_groups_thousands() -> None:
    assert format_number(1234.56, 1) == "1 234,6"
    assert format_number(-2.5, 2) == "-2,50"


def test_rate_units_conversion() -> None:
    settings = UnitSettings(rate="kgf_mm")
    value = settings.parse("10", UnitKind.RATE)
    assert value == pytest.approx(98.0665, rel=1e-6)


def test_selected_units_and_negative_zero_angle() -> None:
    assert UnitSettings(length="in").parse("2", UnitKind.LENGTH) == pytest.approx(50.8)
    assert UnitSettings(length="in").parse("12 см", UnitKind.LENGTH) == pytest.approx(120)
    assert UnitSettings().parse("-0°30′", UnitKind.ANGLE) == pytest.approx(-0.5)
    with pytest.raises(UnitConversionError):
        eval_expression("10**10000")


def test_complex_expression_is_rejected() -> None:
    with pytest.raises(UnitConversionError):
        eval_expression("(-1)**0.5")
