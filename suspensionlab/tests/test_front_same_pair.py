"""Proper rotation of a front tube pair is not a mirror in 3D."""
from copy import deepcopy

import numpy as np
import pytest
from test_front_pair_snapshot import project

from suspensionlab.model.front_pair_snapshot import mirror_front_tube_arm
from suspensionlab.model.front_same_pair import front_same_pair_sides, make_front_same_pair, same_front_tube_arm
from suspensionlab.model.front_tube_arm import front_tube_arm_centerlines, front_tube_arm_points, make_front_tube_arm
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document
from suspensionlab.model.niva_arm_views import FRONT


@pytest.mark.parametrize('arm', FRONT)
def test_same_pair_uses_proper_rotation_and_roundtrips(tmp_path, arm):
    p = project()
    before = p.to_dict()
    sign = -1 if arm.endswith('right') else 1
    source = make_front_tube_arm(p, arm, 10, 2, {'front': {'vertex_mm': [100, 0, 30], 'radius_mm': 20}})
    pair = make_front_same_pair(source)
    path = tmp_path / 'pair.kima'
    write_document(path, 'assembly', pair, overwrite=False)
    first, second = front_same_pair_sides(read_document(path, 'assembly'))
    assert first == source and p.to_dict() == before
    assert second['arm'] != first['arm']
    # All labelled supports align, while an off-plane vertex is on the opposite
    # side compared to reflection: this is a proper rotation, not a mirror.
    np.testing.assert_allclose(front_tube_arm_points(second), np.array(front_tube_arm_points(first)) * [1, -1, 1])
    mirror = mirror_front_tube_arm(first)
    assert second['bends']['front']['vertex_mm'][2] == pytest.approx(-30)
    assert mirror['bends']['front']['vertex_mm'][2] == 30
    restored = same_front_tube_arm(second)
    for a, b in zip(front_tube_arm_centerlines(first), front_tube_arm_centerlines(restored), strict=True):
        np.testing.assert_allclose(a, b, atol=1e-9)
    assert sign in (-1, 1)


def test_unstable_collinear_points_rejected_without_mutating_source():
    p = project()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (100, 0, 0), 'ubj': (200, 0, 0)}.items():
        point = p.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    source = make_front_tube_arm(p, 'front_upper_left', 10, 2)
    saved = deepcopy(source)
    with pytest.raises(KimFormatError, match='orientation'):
        make_front_same_pair(source)
    assert source == saved
    assert mirror_front_tube_arm(source)['arm'] == 'front_upper_right'


def test_strict_new_format(tmp_path):
    source = make_front_tube_arm(project(), 'front_upper_left', 10, 2)
    pair = make_front_same_pair(source)
    for change in (lambda x: x.update(version='0.7'), lambda x: x.update(algorithm='future'),
                   lambda x: x.update(mode='mirror'), lambda x: x['source'].update(arm='panhard')):
        wrong = deepcopy(pair)
        change(wrong)
        with pytest.raises(KimFormatError):
            write_document(tmp_path / 'wrong.kima', 'assembly', wrong, overwrite=False)


def test_skewed_supports_preserve_chirality_not_reflection():
    p = project()
    for code, xyz in {'uca_f_in': (10, 30, 40), 'uca_r_in': (10, -70, 60),
                      'ubj': (110, 110, 70)}.items():
        point = p.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    source = make_front_tube_arm(p, 'front_upper_left', 10, 2,
                                 {'front': {'vertex_mm': [110, 30, 50], 'radius_mm': 20}})
    same, mirror = same_front_tube_arm(source), mirror_front_tube_arm(source)
    def chirality(doc):
        points = np.array(front_tube_arm_points(doc))
        offset = np.array(doc['bends']['front']['vertex_mm']) - points[0]
        return float(np.dot(np.cross(points[1] - points[0], points[2] - points[0]), offset))
    assert abs(chirality(source)) > 1
    assert chirality(same) == pytest.approx(chirality(source), abs=1e-7)
    assert chirality(mirror) == pytest.approx(-chirality(source), abs=1e-7)
