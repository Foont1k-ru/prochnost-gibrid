"""Независимые явные параметры и обратная совместимость формата скелета."""
import json
from copy import deepcopy

import pytest

from suspensionlab.model.fixed_arm_housings import HousingError, make_housing_preview, validate_housings
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, fixed_arm_tube_document
from suspensionlab.model.fixed_arm_skeleton_io import SkeletonFileError, read_skeleton, write_skeleton
from suspensionlab.model.templates import load_template


def housings():
    return {
        'front': {'outer_diameter_mm': 40, 'bore_diameter_mm': 25, 'length_mm': 32,
                  'axis': [1, 2, 3], 'center_on_pivot': True},
        'rear': {'outer_diameter_mm': 52, 'bore_diameter_mm': 31, 'length_mm': 44,
                 'axis': [0, -1, 0], 'center_on_pivot': True},
    }


@pytest.mark.parametrize('mutation', [
    lambda d: d.pop('rear'),
    lambda d: d['front'].update(center_on_pivot=False),
    lambda d: d['rear'].update(center_on_pivot=1),
    lambda d: d['front'].update(axis=[0, 0, 0]),
    lambda d: d['rear'].update(axis=[1, float('nan'), 0]),
    lambda d: d['rear'].update(axis=[1, 2]),
    lambda d: d['front'].update(outer_diameter_mm=25),
    lambda d: d['front'].update(length_mm=0),
    lambda d: d['rear'].update(bore_diameter_mm=True),
    lambda d: d['front'].update(extra=1),
])
def test_bad_housing_parameters_rejected(mutation):
    data = housings()
    mutation(data)
    with pytest.raises(HousingError):
        validate_housings(data)


def test_preview_is_detached_and_source_is_checked():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20)
    tubes = fixed_arm_tube_document(snapshot, project, 10, 2)
    data = housings()
    preview = make_housing_preview(tubes, data)
    data['front']['axis'][0] = 99
    assert preview['housings']['front']['axis'] == [1, 2, 3]
    bad = deepcopy(tubes)
    bad['parts'][0]['geometry']['source']['coordinates_mm'][0][0] += 5
    with pytest.raises(HousingError):
        make_housing_preview(bad, housings())


def test_file_roundtrip_old_and_new_and_reject_unconfirmed(tmp_path):
    project = load_template('ring')
    before = deepcopy(project.to_dict())
    snapshot = capture_fixed_arm(project, -20, 20)
    for h, version in [(None, '1'), (housings(), '2')]:
        path = tmp_path / f'{version}.slarm'
        write_skeleton(path, snapshot, project, 10, 2, {}, h)
        doc = json.loads(path.read_text(encoding='utf-8'))
        assert doc['version'] == version
        loaded = read_skeleton(path, project)
        assert loaded.housings == h and loaded.snapshot == snapshot
    doc['geometry']['housings']['rear']['center_on_pivot'] = False
    path.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(SkeletonFileError):
        read_skeleton(path, project)
    assert project.to_dict() == before
    doc['geometry']['housings']['rear']['center_on_pivot'] = True
    path.write_text(json.dumps(doc), encoding='utf-8')
    project.front.hardpoints['lbj'].x += 0.000001
    with pytest.raises(SkeletonFileError, match='координаты'):
        read_skeleton(path, project)
