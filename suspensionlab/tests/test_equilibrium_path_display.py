"""Форматирование уже рассчитанных точек пути не меняет расчёт."""
from dataclasses import replace

from suspensionlab.core.equilibrium import SpringEquilibrium
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.export.equilibrium_path import PATH_COLUMNS, format_path_sample
from suspensionlab.model.templates import load_template


def test_formatting_preserves_signed_values_and_unknowns() -> None:
    problem = SpringEquilibrium(load_template("ring").front, 230)
    sample = problem.check_path(-2, 1100, step_mm=1).samples[-1]
    before = sample.spring
    row = dict(zip(PATH_COLUMNS, format_path_sample(sample), strict=True))
    assert row["travel"] == f"{sample.travel_mm:.4f}"
    assert row["length"] == f"{sample.spring.length_mm:.4f}"
    assert row["residual"] == f"{sample.residual_n:+.4f}"
    assert row["coil_clearance"] == row["damper_length"] == "—"
    assert row["compression_clearance"] == row["extension_clearance"] == "—"
    assert "не проверен" in row["damper_status"]
    assert sample.spring is before


def test_formatting_known_limits_and_no_fake_zero() -> None:
    problem = SpringEquilibrium(load_template("ring").front, 230, coil_bind_length_mm=150,
                                damper_mount="lower_arm", damper_limits=StrokeLimits(300, 500))
    sample = problem.check_path(2, 1100, step_mm=1).samples[-1]
    assert sample.damper is not None and sample.damper.stroke is not None
    row = dict(zip(PATH_COLUMNS, format_path_sample(sample), strict=True))
    assert row["coil_clearance"] == f"{sample.spring.coil_clearance_mm:.4f}"
    assert row["damper_length"] == f"{sample.damper.length_mm:.4f}"
    assert row["compression_clearance"] == f"{sample.damper.stroke.compression_clearance_mm:.4f}"
    assert row["extension_clearance"] == f"{sample.damper.stroke.extension_clearance_mm:.4f}"
    assert row["damper_status"] == "Между заданными упорами"
    unknown = replace(sample, damper=replace(sample.damper, stroke=None))
    row = dict(zip(PATH_COLUMNS, format_path_sample(unknown), strict=True))
    assert row["compression_clearance"] == "—" and row["extension_clearance"] == "—"
    assert row["damper_status"] == "Упоры амортизатора не заданы"


def test_formatting_does_not_hide_damper_error() -> None:
    problem = SpringEquilibrium(load_template("ring").front, 230, damper_mount="lower_arm")
    sample = problem.check_path(0, 1000).samples[0]
    assert sample.damper is not None
    sample = replace(sample, damper=replace(sample.damper, error="Ошибка опор"))
    row = dict(zip(PATH_COLUMNS, format_path_sample(sample), strict=True))
    assert row["damper_status"] == "Ошибка опор"
