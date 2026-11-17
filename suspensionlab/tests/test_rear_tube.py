"""Снимки задней трубы, строгая проверка, совместимость и защита копий."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document
from suspensionlab.model.rear_tube import make_rear_tube, rear_tube_centerline, validate_rear_tube


def project():
    p = Project.create_default()
    p.rear.type_code = 'live_axle_coil'
    p.rear.layout = '4link_panhard'
    p.rear.ensure_points(overwrite=True)
    for code, xyz in {'ll_in_l': (0, 0, 0), 'll_out_l': (100, 100, 0)}.items():
        point = p.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    return p


def test_all_rear_tubes_roundtrip_and_bend_is_copied(tmp_path):
    p = project()
    before = p.to_dict()
    for key in ('rear_upper_left', 'rear_upper_right', 'rear_lower_left', 'rear_lower_right', 'panhard'):
        straight = make_rear_tube(p, key, 10, 2)
        assert straight['version'] == '0.4' and len(rear_tube_centerline(straight)) == 2
        path = tmp_path / f'{key}.kima'
        write_document(path, 'assembly', straight, overwrite=False)
        assert read_document(path, 'assembly') == straight
    spec = {'vertex_mm': [100, 0, 0], 'radius_mm': 20}
    curved = make_rear_tube(p, 'rear_lower_left', 10, 2, spec)
    spec['vertex_mm'][0] = -1
    assert curved['bend']['vertex_mm'] == [100, 0, 0] and len(rear_tube_centerline(curved)) > 3
    path = tmp_path / 'curved.kima'
    write_document(path, 'assembly', curved, overwrite=False)
    assert read_document(path, 'assembly') == curved and p.to_dict() == before
    original = path.read_bytes()
    with pytest.raises((KimFormatError, OSError)):
        write_document(path, 'assembly', straight, overwrite=False)
    assert path.read_bytes() == original


def test_incompatible_or_incomplete_sources_and_invalid_dimensions_rejected():
    p = project()
    for radius, wall in ((10, 10), (10, 0), (float('nan'), 2), (True, 1)):
        with pytest.raises(KimFormatError):
            make_rear_tube(p, 'rear_lower_left', radius, wall)
    for bend in ({'vertex_mm': [100, 0], 'radius_mm': 20}, {'vertex_mm': [100, 0, 0], 'radius_mm': 1000},
                 {'vertex_mm': [float('inf'), 0, 0], 'radius_mm': 20}, {'vertex_mm': [100, 0, 0]}):
        with pytest.raises(KimFormatError):
            make_rear_tube(p, 'rear_lower_left', 10, 2, bend)
    doc = make_rear_tube(p, 'rear_lower_left', 10, 2)
    for mutate in (lambda d: d.update(arm=[]), lambda d: d.update(frame='front'),
                   lambda d: d.update(extra=1), lambda d: d.update(scheme=None),
                   lambda d: d['scheme']['rear_axle'].update(layout='4link_watt')):
        broken = deepcopy(doc)
        mutate(broken)
        with pytest.raises(KimFormatError):
            validate_rear_tube(broken)
    p.rear.layout = '4link_watt'
    with pytest.raises(KimFormatError):
        make_rear_tube(p, 'rear_lower_left', 10, 2)


def test_original_snapshot_unchanged_after_project_updates():
    p = project()
    doc = make_rear_tube(p, 'rear_lower_left', 10, 2)
    original = deepcopy(doc)
    p.rear.hardpoints['ll_out_l'].y += 20
    other = make_rear_tube(p, 'rear_lower_left', 10, 2)
    assert other != doc and doc == original
