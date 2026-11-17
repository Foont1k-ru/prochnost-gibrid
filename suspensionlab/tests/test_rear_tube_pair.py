"""Парные трубы: отражение и вращение — принципиально разные операции."""
from copy import deepcopy

import numpy as np
import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document
from suspensionlab.model.rear_tube import make_rear_tube, rear_tube_centerline
from suspensionlab.model.rear_tube_pair import make_paired_rear_tube


def make_project(right_start=(0, 0, 0), right_end=(100, -100, 0)):
    p = Project.create_default()
    p.rear.type_code, p.rear.layout = 'live_axle_coil', '4link_panhard'
    p.rear.ensure_points(overwrite=True)
    for code, xyz in {'ll_in_l': (0, 0, 0), 'll_out_l': (100, 100, 0),
                      'll_in_r': right_start, 'll_out_r': right_end}.items():
        pt = p.rear.hardpoints[code]
        pt.x, pt.y, pt.z = xyz
    return p


def test_mirror_and_same_are_different_and_snapshot_is_unchanged(tmp_path):
    p = make_project()
    original_project = p.to_dict()
    doc = make_rear_tube(p, 'rear_lower_left', 10, 2, {'vertex_mm': [100, 0, 0], 'radius_mm': 20})
    original = deepcopy(doc)
    mirrored = make_paired_rear_tube(doc, 'mirror')
    same = make_paired_rear_tube(doc, 'same')
    assert mirrored['bend']['vertex_mm'] == pytest.approx([100, 0, 0])
    assert same['bend']['vertex_mm'] == pytest.approx([0, -100, 0], abs=1e-10)
    assert mirrored['arm'] == same['arm'] == 'rear_lower_right'
    # Every segment of the sampled centreline retains its length, not only endpoints.
    line = np.array(rear_tube_centerline(doc))
    for pair in (same, mirrored, make_paired_rear_tube(doc, 'same', 75)):
        target = np.array(rear_tube_centerline(pair))
        assert np.linalg.norm(np.diff(target, axis=0), axis=1) == pytest.approx(
            np.linalg.norm(np.diff(line, axis=0), axis=1), abs=1e-9)
        path = tmp_path / f"{pair['bend']['vertex_mm'][1]}.kima"
        write_document(path, 'assembly', pair)
        assert read_document(path, 'assembly') == pair
    assert doc == original and p.to_dict() == original_project
    assert make_paired_rear_tube(mirrored, 'mirror') == doc
    assert make_paired_rear_tube(same, 'same')['bend']['vertex_mm'] == pytest.approx(
        doc['bend']['vertex_mm'], abs=1e-9)


def test_opposite_points_and_unsupported_panhard_never_guessed():
    p = make_project(right_start=(0, 1, 0), right_end=(100, -100, 0))
    doc = make_rear_tube(p, 'rear_lower_left', 10, 2)
    for mode in ('mirror', 'same'):
        with pytest.raises(KimFormatError):
            make_paired_rear_tube(doc, mode)
    for roll in (181, -181, float('nan'), True):
        with pytest.raises(KimFormatError):
            make_paired_rear_tube(doc, 'same', roll)
    p = make_project()
    doc = make_rear_tube(p, 'panhard', 10, 2)
    with pytest.raises(KimFormatError):
        make_paired_rear_tube(doc, 'mirror')


def test_antiparallel_rotation_is_proper_and_preserves_distance():
    p = make_project(right_start=(300, 0, 0), right_end=(200, -100, 0))
    doc = make_rear_tube(p, 'rear_lower_left', 10, 2, {'vertex_mm': [100, 0, 0], 'radius_mm': 20})
    pair = make_paired_rear_tube(doc, 'same')
    line, other = np.array(rear_tube_centerline(doc)), np.array(rear_tube_centerline(pair))
    assert np.linalg.norm(np.diff(other, axis=0), axis=1) == pytest.approx(
        np.linalg.norm(np.diff(line, axis=0), axis=1), abs=1e-9)
    assert other[0] == pytest.approx([300, 0, 0]) and other[-1] == pytest.approx([200, -100, 0])
