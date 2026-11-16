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


def test_distance_summary_metadata_uses_row_numbers_and_full_precision():
    source = ((0., 0., 0.), (3., 0., 0.), (0., 4., 0.), (0., 0., 12.))
    target = ((0., 0., 0.), (6., 0., 0.), (0., 8., 0.), (0., 0., 9.1234567890123))
    mask = (True, True, True, False)
    result = evaluate_registration(source, target, mask)
    records = tuple(replace(record, xyz=target[i]) for i, record in
                    enumerate(capture_points(Project.create_default())[:4]))
    metadata = dict(registration_report(result, records, source, mask, str).metadata)
    assert metadata['fit_segments_count'] == '3'
    assert metadata['fit_segments_worst_row_1'] == '2'
    assert metadata['fit_segments_worst_row_2'] == '3'
    assert float(metadata['fit_segments_worst_project_minus_cad_mm']) == 5
    assert metadata['control_segments_count'] == '3'
    assert result.control_distances is not None
    assert float(metadata['control_segments_rms_difference_mm']) == result.control_distances.rms_difference_mm
    assert metadata['cad_registration.distance_report_warning'] == 'cad_registration.distance_warning'
    no_control = evaluate_registration(source[:3], target[:3], mask[:3])
    no_metadata = dict(registration_report(no_control, records[:3], source[:3], mask[:3], str).metadata)
    assert no_metadata['control_segments_count'] == '0'
    assert 'control_segments_worst_row_1' not in no_metadata


def test_distance_report_all_pairs_precision_and_spreadsheet_safety(tmp_path):
    from suspensionlab.export.cad_registration_report import distance_report

    cad = ((0., 0., 0.), (3., 0., 0.), (0., 4., 0.), (0., 0., 12.))
    target = ((0., 0., 0.), (6.123456789012, 0., 0.), (0., 8., 0.), (0., 0., 9.))
    mask = (True, True, True, False)
    result = evaluate_registration(cad, target, mask)
    records = tuple(replace(record, xyz=target[i], code='=BAD' if i == 3 else record.code)
                    for i, record in enumerate(capture_points(Project.create_default())[:4]))
    report = distance_report(result, records, mask, str)
    assert len(report.rows) == 6
    path = tmp_path / 'distances.csv'
    write_csv_report(report, path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream, delimiter=';'))
    idx = next(i for i, row in enumerate(rows) if row and row[0] == 'row_1')
    data = [dict(zip(rows[idx], row, strict=True)) for row in rows[idx + 1:]]
    assert [(r['row_1'], r['row_2']) for r in data] == [
        ('1', '2'), ('1', '3'), ('1', '4'), ('2', '3'), ('2', '4'), ('3', '4')]
    assert data[0]['project_length_mm'] == repr(target[1][0])
    assert data[2]['point_code_2'] == "'=BAD" and data[2]['purpose_2'] == 'control'
    assert float(data[2]['project_minus_cad_mm']) == -3
    assert float(data[2]['absolute_difference_mm']) == 3
    with pytest.raises(ValueError):
        distance_report(result, records[:3], mask, str)
