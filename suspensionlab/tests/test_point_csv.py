"""Формат CSV точек: проверка до изменения проекта и защита экспорта."""
import csv

import pytest

from suspensionlab.i18n import tr
from suspensionlab.model.entities import Hardpoint, Project
from suspensionlab.model.point_csv import (
    HEADERS,
    MAX_BYTES,
    PointCSVError,
    capture_points,
    read_points_csv,
    write_points_csv,
)


def make_file(path, project):
    records = capture_points(project)
    write_points_csv(path, records, tr)
    return records


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.reader(stream))


def save_rows(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows(rows)


def test_round_trip_order_independent_metadata_is_informational(tmp_path):
    project = Project.create_default()
    records = make_file(tmp_path / 'points.csv', project)
    path = tmp_path / 'points.csv'
    rows = csv_rows(path)
    rows[1][5] = '-123.456789012345'
    rows[1][3] = 'altered label'
    rows[1][8:12] = ['True'] * 4
    save_rows(path, [rows[0], *reversed(rows[1:])])
    before = project.front.hardpoints[records[0].code].as_tuple()
    changes = read_points_csv(path, records)
    assert len(changes) == 1 and changes[0].new[0] == -123.456789012345
    assert project.front.hardpoints[records[0].code].as_tuple() == before
    assert changes[0].axes == ('x',)


@pytest.mark.parametrize('change, expected', [
    (lambda r: r[0].reverse(), 'header'),
    (lambda r: r[1].pop(), 'columns'),
    (lambda r: r[1].__setitem__(0, 'unknown'), 'unknown'),
    (lambda r: r.append(r[1][:]), 'duplicate'),
    (lambda r: r[1].__setitem__(1, 'wrong'), 'mismatch'),
    (lambda r: r[1].__setitem__(4, 'wrong'), 'mismatch'),
    (lambda r: r[1].__setitem__(5, '=1+2'), 'number'),
    (lambda r: r[1].__setitem__(5, '12,5'), 'number'),
    (lambda r: r[1].__setitem__(5, 'nan'), 'number'),
    (lambda r: r[1].__setitem__(5, '1e309'), 'number'),
    (lambda r: r[1].__setitem__(5, '1000000001'), 'number'),
    (lambda r: r.pop(), 'missing'),
])
def test_bad_files_are_rejected(tmp_path, change, expected):
    path = tmp_path / 'points.csv'
    records = make_file(path, Project.create_default())
    rows = csv_rows(path)
    change(rows)
    save_rows(path, rows)
    with pytest.raises(PointCSVError) as error:
        read_points_csv(path, records)
    assert error.value.code == expected


def test_current_locks_not_file_locks_and_zones(tmp_path):
    project = Project.create_default()
    p = project.front.hardpoints['spring_lo']
    p.zone_min, p.zone_max = (-10, 500, 100), (10, 530, 160)
    project.locks['front.point.spring_lo.x'] = True
    path = tmp_path / 'points.csv'
    records = make_file(path, project)
    rows = csv_rows(path)
    line = next(r for r in rows[1:] if r[0] == 'front' and r[2] == 'spring_lo')
    line[8:12] = ['False'] * 4
    line[5] = '5'
    save_rows(path, rows)
    with pytest.raises(PointCSVError) as error:
        read_points_csv(path, records)
    assert error.value.code == 'locked' and error.value.axis == 'X'
    line[5] = str(p.x)
    line[7] = '200'
    save_rows(path, rows)
    changes = read_points_csv(path, records)
    assert changes[0].outside_zone is True and changes[0].axes == ('z',)
    p.locked = True
    with pytest.raises(PointCSVError) as error:
        read_points_csv(path, capture_points(project))
    assert error.value.code == 'locked'


def test_encoding_format_size_and_file_failure(tmp_path):
    records = capture_points(Project.create_default())
    path = tmp_path / 'points.csv'
    with pytest.raises(PointCSVError, match='read'):
        read_points_csv(path, records)
    path.write_bytes(b'\xff')
    with pytest.raises(PointCSVError, match='encoding'):
        read_points_csv(path, records)
    path.write_bytes(b'a' * (MAX_BYTES + 1))
    with pytest.raises(PointCSVError, match='size'):
        read_points_csv(path, records)
    path.write_text(','.join(HEADERS) + '\n"unclosed', encoding='utf8')
    with pytest.raises(PointCSVError, match='format'):
        read_points_csv(path, records)


def test_csv_formula_text_protection_and_ambiguous_codes(tmp_path):
    project = Project.create_default()
    project.front.hardpoints['=2+3'] = Hardpoint('=2+3', 1, 2, 3)
    path = tmp_path / 'points.csv'
    records = make_file(path, project)
    row = next(r for r in csv_rows(path) if r[2] == "'=2+3")
    assert row[3] == "'=2+3"
    assert not read_points_csv(path, records)
    # Existing files written before spreadsheet protection can also be read.
    rows = csv_rows(path)
    next(r for r in rows if r[2] == "'=2+3")[2] = '=2+3'
    save_rows(path, rows)
    assert not read_points_csv(path, records)
    project.front.hardpoints["'=2+3"] = Hardpoint("'=2+3", 1, 2, 3)
    with pytest.raises(PointCSVError, match='ambiguous'):
        read_points_csv(path, capture_points(project))


def test_atomic_export_preserves_existing_file_on_failure(tmp_path, monkeypatch):
    path = tmp_path / 'points.csv'
    path.write_bytes(b'old')
    def fail(*args):
        raise OSError('failure')
    monkeypatch.setattr('suspensionlab.model.point_csv.os.replace', fail)
    with pytest.raises(OSError):
        write_points_csv(path, capture_points(Project.create_default()), tr)
    assert path.read_bytes() == b'old'
    assert not list(tmp_path.glob('.suspensionlab-points-*.tmp'))
