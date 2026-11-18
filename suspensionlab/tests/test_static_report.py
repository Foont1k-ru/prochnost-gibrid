"""Численный отчёт статики: значения, пропуски, стороны и CSV-защита."""
from __future__ import annotations

import csv
from dataclasses import replace

import pytest

from suspensionlab.core.analysis import analyze_corner
from suspensionlab.core.stroke import StrokeLimits
from suspensionlab.export.csv_report import CSVReport, write_csv_report
from suspensionlab.export.static_report import static_report_rows
from suspensionlab.i18n import tr
from suspensionlab.model.templates import load_template


def rows_by_name(rows):
    return {row[0]: row[1:] for row in rows}


def test_static_report_full_precision_conflict_and_right_side(tmp_path):
    project = load_template("ring")
    result = analyze_corner(project.front, project.vehicle, [0], side="right", spring_mount="lower_arm",
                            static_spring_length_mm=320, coil_bind_length_mm=115,
                            damper_mount="lower_arm", damper_limits=StrokeLimits(205, 325))
    sample = result.samples[0]
    assert sample and sample.spring and sample.spring.state and sample.damper and sample.damper.stroke
    columns, rows = static_report_rows(sample, project.front, "right")
    data = rows_by_name(rows)
    key = lambda name: tr(f"analysis.static.report.metric.{name}")  # noqa: E731
    assert float(data[key("damper_length")][0]) == sample.damper.length_mm
    assert float(data[key("damper_extension_clearance")][0]) == sample.damper.stroke.extension_clearance_mm
    assert float(data[key("damper_extension_clearance")][0]) < -69
    assert "Превышен упор отбоя" in data[key("damper_status")][0]
    assert float(data[key("spring_length")][0]) == 320
    assert float(data[key("spring_force")][0]) == 0
    assert float(data[key("spring_lo_y")][0]) == -project.front.hardpoints["spring_lo"].y
    assert float(data[key("spring_offset")][0]) == 320 - float(data[key("spring_mount_distance")][0])
    assert len(rows) == len(data) and all("‹" not in str(row) for row in rows)
    # Непроверенная строка ошибки и метаданные не должны превратиться в формулы.
    evil_sample = replace(sample, damper=replace(sample.damper, error="=external()"))
    _, evil_rows = static_report_rows(evil_sample, project.front, "right")
    path = write_csv_report(CSVReport((("имя", "=unsafe"),), columns, evil_rows), tmp_path / "static.csv")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as f:
        data_rows = list(csv.reader(f, delimiter=";"))
    assert data_rows[0][1] == "'=unsafe"
    assert any(row[0] == key("damper_status") and row[1] == "'=external()" for row in data_rows if row)
    assert any(row[0] == key("damper_extension_clearance") and float(row[1]) < 0 for row in data_rows if row)


def test_disabled_and_unknown_are_not_zeros():
    project = load_template("ring")
    sample = analyze_corner(project.front, project.vehicle, [0]).samples[0]
    assert sample
    _, rows = static_report_rows(sample, project.front, "left")
    data = rows_by_name(rows)
    metric = lambda name: tr(f"analysis.static.report.metric.{name}")  # noqa: E731
    assert data[metric("spring_status")][0] == tr("analysis.static.report.disabled")
    assert data[metric("damper_length")][0] == "—"
    assert data[metric("spring_lo_x")][0] == "—"
    result = analyze_corner(project.front, project.vehicle, [0], spring_mount="lower_arm",
                            static_spring_length_mm=230, damper_mount="lower_arm")
    assert result.samples[0]
    _, rows = static_report_rows(result.samples[0], project.front, "left")
    data = rows_by_name(rows)
    assert data[metric("spring_clearance")][0] == "—"
    assert data[metric("damper_extension_clearance")][0] == "—"
    assert "не заданы" in data[metric("damper_status")][0]
    assert float(data[metric("spring_force")][0]) > 0


def test_nonstatic_and_invalid_side_rejected():
    project = load_template("ring")
    samples = analyze_corner(project.front, project.vehicle, [0, 1]).samples
    assert samples[0] and samples[1]
    with pytest.raises(ValueError):
        static_report_rows(samples[1], project.front, "left")
    with pytest.raises(ValueError):
        static_report_rows(samples[0], project.front, "centre")
