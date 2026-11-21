"""Версионированный файл не меняет проект и не доверяет записанным результатам."""
import json
from copy import deepcopy

import pytest

from suspensionlab.model import fixed_arm_skeleton_io as io
from suspensionlab.model.fixed_arm_skeleton import capture_fixed_arm, preview_fixed_arm
from suspensionlab.model.templates import load_template


def sample():
    project = load_template('ring')
    snapshot = capture_fixed_arm(project, -20, 20, spacing_mm=10)
    anchors = preview_fixed_arm(snapshot, project, 10, 2).anchors
    a, b = anchors[0], anchors[2]
    vertex = [(a[i] + b[i]) / 2 for i in range(3)]
    vertex[2] += 50
    return project, snapshot, {'front': {'vertex_mm': vertex, 'radius_mm': 20}}


def test_roundtrip_recalculates_and_keeps_exact_anchors(tmp_path, monkeypatch):
    project, snapshot, bends = sample()
    before = deepcopy(project.to_dict())
    path = tmp_path / 'skeleton.slarm'
    io.write_skeleton(path, snapshot, project, 10, 2, bends)
    original = path.read_bytes()
    calls = []
    original_capture = io.capture_fixed_arm
    def observed(*args, **kwargs):
        calls.append((args, kwargs))
        return original_capture(*args, **kwargs)
    monkeypatch.setattr(io, 'capture_fixed_arm', observed)
    loaded = io.read_skeleton(path, project)
    assert len(calls) == 1 and loaded.snapshot == snapshot
    assert loaded.bends == bends and loaded.radius_mm == 10 and loaded.wall_mm == 2
    assert preview_fixed_arm(loaded.snapshot, project, 10, 2, loaded.bends) == preview_fixed_arm(snapshot, project, 10, 2, bends)
    assert project.to_dict() == before and path.read_bytes() == original


def test_source_change_including_sub_rounding_blocks_open_and_save(tmp_path):
    project, snapshot, bends = sample()
    path = tmp_path / 'skeleton.slarm'
    io.write_skeleton(path, snapshot, project, 10, 2, bends)
    point = project.front.hardpoints['lbj']
    point.x += 0.000001
    with pytest.raises(io.SkeletonFileError, match='координаты'):
        io.read_skeleton(path, project)
    target = tmp_path / 'new.slarm'
    with pytest.raises(io.SkeletonFileError, match='отличается'):
        io.write_skeleton(target, snapshot, project, 10, 2, bends)
    assert not target.exists()
    point.x += 1
    with pytest.raises(io.SkeletonFileError, match='изменённой'):
        io.read_skeleton(path, project)


def test_tampered_conditions_and_bends_rejected(tmp_path):
    project, snapshot, bends = sample()
    data = io.make_skeleton_data(snapshot, project, 10, 2, bends)
    mutations = [
        lambda d: d.update(version='future'),
        lambda d: d['calculation'].update(algorithm='unknown'),
        lambda d: d['calculation']['travels_mm'].__setitem__(0, -19),
        lambda d: d['calculation'].update(spacing_mm=0),
        lambda d: d['calculation'].update(max_residual_mm=float('nan')),
        lambda d: d['calculation'].update(max_step_mm=True),
        lambda d: d['geometry'].update(radius_mm=10.001),
        lambda d: d['geometry']['bends']['front'].update(radius_mm=100000),
        lambda d: d['geometry']['bends']['front']['vertex_mm'].__setitem__(0, float('inf')),
        lambda d: d['project']['front_axle']['hardpoints']['lbj'].update(x=999),
        lambda d: d['raw_solver_points'][0].__setitem__(0, True),
        lambda d: d.update(unexpected='field'),
    ]
    for i, mutate in enumerate(mutations):
        altered = deepcopy(data)
        mutate(altered)
        path = tmp_path / f'bad-{i}.slarm'
        path.write_text(json.dumps(altered), encoding='utf-8')
        with pytest.raises(io.SkeletonFileError):
            io.read_skeleton(path, project)


def test_duplicate_keys_unknown_suffix_and_invalid_input(tmp_path):
    project, snapshot, bends = sample()
    path = tmp_path / 'duplicate.slarm'
    path.write_text('{"format":"x", "format":"y"}', encoding='utf-8')
    with pytest.raises(io.SkeletonFileError):
        io.read_skeleton(path, project)
    with pytest.raises(io.SkeletonFileError):
        io.write_skeleton(tmp_path / 'other.json', snapshot, project, 10, 2, bends)
    with pytest.raises(io.SkeletonFileError):
        io.write_skeleton(tmp_path / 'bad.slarm', snapshot, project, 1, 2, bends)
    assert not (tmp_path / 'bad.slarm').exists()


def test_existing_file_symlink_and_failed_write_are_not_overwritten(tmp_path):
    project, snapshot, bends = sample()
    target = tmp_path / 'existing.slarm'
    target.write_bytes(b'unchanged')
    with pytest.raises(io.SkeletonFileError):
        io.write_skeleton(target, snapshot, project, 10, 2, bends)
    assert target.read_bytes() == b'unchanged'
    link = tmp_path / 'link.slarm'
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks unavailable')
    with pytest.raises(io.SkeletonFileError):
        io.write_skeleton(link, snapshot, project, 10, 2, bends)
    assert target.read_bytes() == b'unchanged'
    assert not list(tmp_path.glob('.slarm-*.tmp'))


def test_a_recorded_residual_is_not_treated_as_a_new_calculation(tmp_path, monkeypatch):
    project, snapshot, bends = sample()
    data = io.make_skeleton_data(snapshot, project, 10, 2, bends)
    data['calculation']['max_residual_mm'] = 0
    path = tmp_path / 'input.slarm'
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(io, 'capture_fixed_arm', lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('failed')))
    with pytest.raises(io.SkeletonFileError):
        io.read_skeleton(path, project)
