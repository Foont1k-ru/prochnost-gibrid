import csv
from dataclasses import replace

import pytest

from suspensionlab.core.cad_registration import evaluate_registration
from suspensionlab.export.cad_registration_report import registration_report
from suspensionlab.export.csv_report import write_csv_report
from suspensionlab.model.entities import Project
from suspensionlab.model.point_csv import capture_points


def test_complete_report_full_precision_and_spreadsheet_protection(tmp_path):
    source = ((0., 0., 0.), (10., 0., 0.), (0., 10., 0.), (0., 0., 10.))
    target = (*source[:3], (1.234567890123, 2., 13.))
    mask = (True, True, True, False)
    result = evaluate_registration(source, target, mask)
    base = capture_points(Project.create_default())[:4]
    records = tuple(replace(record, xyz=target[i], code='=BAD' if i == 3 else record.code)
                    for i, record in enumerate(base))
    report = registration_report(result, records, source, mask, lambda s: s)
    path = tmp_path / 'result.csv'
    write_csv_report(report, path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream, delimiter=';'))
    header_row = next(i for i, row in enumerate(rows) if row and row[0] == 'row')
    head, data = rows[header_row], rows[header_row + 1:]
    control = dict(zip(head, data[3], strict=True))
    assert control['purpose'] == 'control' and control['point_code'] == "'=BAD"
    assert float(control['project_x_mm']) == target[3][0]
    assert float(control['delta_z_mm']) == pytest.approx(-3)
    assert float(control['distance_mm']) == pytest.approx(result.control_max_mm)
    assert ['control_count', '1'] in rows
    assert len(data) == 4


def test_inconsistent_report_is_rejected():
    points = ((0., 0., 0.), (10., 0., 0.), (0., 10., 0.))
    result = evaluate_registration(points, points, (True, True, True))
    records = capture_points(Project.create_default())[:3]
    with pytest.raises(ValueError):
        registration_report(result, records[:2], points, (True, True, True), str)


def test_report_marks_approximate_surface_and_rejects_invalid_source():
    points = ((0., 0., 0.), (10., 0., 0.), (0., 10., 0.))
    mask = (True, True, True)
    result = evaluate_registration(points, points, mask)
    records = capture_points(Project.create_default())[:3]
    sources = ('surface_preview', 'manual_or_edited', 'surface_preview')
    report = registration_report(result, records, points, mask, str, sources)
    source_column = report.columns.index('cad_input')
    assert tuple(row[source_column] for row in report.rows) == sources
    for invalid in (('surface_preview',), ('surface_preview', 'manual_or_edited', '=formula')):
        with pytest.raises(ValueError):
            registration_report(result, records, points, mask, str, invalid)


def test_source_check_metadata_is_aggregate_only():
    from suspensionlab.core.cad_source_guard import summarize_sources
    points = ((0., 0., 0.), (10., 0., 0.), (0., 10., 0.))
    mask = (True, True, True)
    result = evaluate_registration(points, points, mask)
    records = capture_points(Project.create_default())[:3]
    sources = ('surface_preview', 'manual_or_edited', 'surface_preview')
    summary = summarize_sources((b'x' * 32, None, b'x' * 32))
    report = registration_report(result, records, points, mask, str, sources, summary)
    assert ('surface_points_with_digest', '2') in report.metadata
    assert ('manual_or_edited_unverified', '1') in report.metadata
    assert ('distinct_surface_content_at_load', '1') in report.metadata
    assert 'x' * 32 not in repr(report)
    with pytest.raises(ValueError):
        registration_report(result, records, points, mask, str, sources,
                            summarize_sources((b'x' * 32, None, b'y' * 32)))
