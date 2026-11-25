"""Независимые входные данные и файл не содержат результатов расчёта подвески."""
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm
from suspensionlab.model.fixed_arm_skeleton_io import SkeletonFileError, read_skeleton, write_skeleton
from suspensionlab.model.free_arm import FreeArmBend, FreeArmDraft, FreeArmError
from suspensionlab.model.free_arm_io import FreeArmFileError, from_data, read_free_arm, to_data, write_free_arm
from suspensionlab.model.templates import load_template


def draft():
    return FreeArmDraft((0, 0, 0), (0, 200, 0), (300, 100, 10), 10, 2,
                        FreeArmBend((150, 20, 50), 20))


def test_immutable_independent_points_and_bend():
    source = [0, 0, 0]
    value = FreeArmDraft(source, [0, 200, 0], [300, 100, 10], 10, 2)
    source[0] = 99
    assert value.front_mm == (0, 0, 0)
    with pytest.raises(FrozenInstanceError):
        value.wall_mm = 4
    changed = replace(value, front_mm=(20, 0, 0))
    assert changed.front_mm == (20, 0, 0) and value.front_mm == (0, 0, 0)
    bent = draft()
    lines = bent.centerlines()
    assert lines[0][0] == bent.front_mm and lines[0][-1] == bent.outer_mm
    assert lines[1] == (bent.rear_mm, bent.outer_mm)
    assert len(lines[0]) > 3


@pytest.mark.parametrize('change', [
    {'front_mm': (False, 0, 0)}, {'front_mm': (float('nan'), 0, 0)},
    {'outer_mm': (0, 0, 0)}, {'rear_mm': (1e7, 0, 0)}, {'outer_mm': (1, 2)},
    {'radius_mm': 0}, {'wall_mm': 10}, {'wall_mm': True}, {'radius_mm': float('inf')},
    {'front_bend': {'vertex_mm': [1, 2, 3], 'radius_mm': 20}},
    {'front_bend': FreeArmBend((150, 50, 5), 20)},  # collinear with front and outer
    {'front_bend': FreeArmBend((150, 20, 50), 9)},
])
def test_invalid_candidate_does_not_change_previous(change):
    value = draft()
    original = value.centerlines()
    with pytest.raises(FreeArmError):
        replace(value, **change)
    assert value.centerlines() == original


def test_roundtrip_independent_and_existing_format_not_confused(tmp_path):
    project = load_template('ring')
    old_project = deepcopy(project.to_dict())
    original = draft()
    data = to_data(original)
    assert data['source'] == 'independent' and data['frame'] == 'independent_xyz'
    assert not {'project', 'calculation', 'raw_solver_points'} & data.keys()
    path = tmp_path / 'free.slarm'
    write_free_arm(path, original)
    assert read_free_arm(path) == original
    with pytest.raises(SkeletonFileError):
        read_skeleton(path, project)
    snapshot = capture_fixed_arm(project, 0, 0)
    fixed_path = tmp_path / 'fixed.slarm'
    write_skeleton(fixed_path, snapshot, project, 10, 2, {})
    with pytest.raises(FreeArmFileError):
        read_free_arm(fixed_path)
    assert read_skeleton(fixed_path, project).snapshot == snapshot
    assert project.to_dict() == old_project


def test_invalid_tampered_and_duplicate_json_rejected(tmp_path):
    data = to_data(draft())
    variations = []
    for key, value in [('format', 'other'), ('version', '2'), ('source', 'snapshot'),
                       ('units', 'in'), ('frame', 'vehicle_front_left')]:
        altered = deepcopy(data)
        altered[key] = value
        variations.append(altered)
    variations += [dict(data, project={}), dict(data, calculation={})]
    for change in (lambda d: d['anchors_mm']['front'].__setitem__(0, float('nan')),
                   lambda d: d['tube'].update(wall_mm=True),
                   lambda d: d['bends']['front'].update(radius_mm=-1),
                   lambda d: d['bends'].update(other=None)):
        altered = deepcopy(data)
        change(altered)
        variations.append(altered)
    for index, value in enumerate(variations):
        path = tmp_path / f'bad{index}.slarm'
        path.write_text(json.dumps(value), encoding='utf-8')
        with pytest.raises(FreeArmFileError):
            read_free_arm(path)
    duplicate = tmp_path / 'duplicate.slarm'
    duplicate.write_text('{"format":"x","format":"y"}', encoding='utf-8')
    with pytest.raises(FreeArmFileError):
        read_free_arm(duplicate)
    with pytest.raises(FreeArmFileError):
        from_data({'format': 'suspensionlab-free-arm'})


def test_no_overwrite_symlink_or_wrong_suffix(tmp_path):
    value = draft()
    path = tmp_path / 'original.slarm'
    path.write_bytes(b'unchanged')
    with pytest.raises(FreeArmFileError):
        write_free_arm(path, value)
    assert path.read_bytes() == b'unchanged'
    with pytest.raises(FreeArmFileError):
        write_free_arm(tmp_path / 'wrong.json', value)
    link = tmp_path / 'link.slarm'
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks unavailable')
    with pytest.raises(FreeArmFileError):
        write_free_arm(link, value)
    assert path.read_bytes() == b'unchanged'
    assert not list(tmp_path.glob('.slarm-free-*.tmp'))
