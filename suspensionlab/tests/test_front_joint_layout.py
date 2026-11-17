"""Самодостаточные условные узлы в экспериментальной передней компоновке."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.front_joint_layout import make_front_joint_layout
from suspensionlab.model.front_pair_snapshot import make_front_pair_snapshot
from suspensionlab.model.front_tube_arm import make_front_tube_arm
from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document


def layout():
    p = Project.create_default()
    arm = make_front_tube_arm(p, 'front_upper_left', 10, 2)
    pair = make_front_pair_snapshot(arm)
    return make_front_joint_layout(pair, make_joint_concept('ball', DEFAULTS['ball']),
                                   make_joint_concept('bushing', DEFAULTS['bushing']))


def test_round_trip_snapshot_and_deep_copy(tmp_path):
    doc = layout()
    original = deepcopy(doc)
    path = tmp_path / 'layout.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    doc['ball']['parameters']['pin_length_mm'] = 48
    assert read_document(path, 'assembly') == original
    assert original['version'] == '0.9' and original['pair']['version'] == '0.7'


def test_invalid_embedded_joints_and_schemas_rejected(tmp_path):
    doc = layout()
    tests = [lambda d: d.update(extra='https://example.com/unknown.step'),
             lambda d: d.update(ball=d['bushing']), lambda d: d['pair'].update(algorithm='future'),
             lambda d: d['ball']['parameters'].update(pin_radius_mm=50), lambda d: d.update(version='1.0')]
    for mutate in tests:
        broken = deepcopy(doc)
        mutate(broken)
        with pytest.raises(KimFormatError):
            write_document(tmp_path / 'invalid.kima', 'assembly', broken, overwrite=False)


def test_same_layout_format_and_strict_pair_version(tmp_path):
    from suspensionlab.model.front_same_pair import make_front_same_pair

    p = Project.create_default()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (0, -100, 0), 'ubj': (100, 100, 0)}.items():
        point = p.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    same = make_front_same_pair(make_front_tube_arm(p, 'front_upper_left', 10, 2))
    ball, bushing = make_joint_concept('ball', DEFAULTS['ball']), make_joint_concept('bushing', DEFAULTS['bushing'])
    doc = make_front_joint_layout(same, ball, bushing)
    path = tmp_path / 'same-layout.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    assert doc['version'] == '0.12' and doc['pair']['version'] == '0.11'
    assert read_document(path, 'assembly') == doc
    for mutation in (lambda d: d.update(version='0.9'), lambda d: d.update(algorithm='front-joint-layout-v1'),
                     lambda d: d.update(pair=layout()['pair']), lambda d: d.update(extra='joint.step'),
                     lambda d: d.update(ball=d['bushing'])):
        invalid = deepcopy(doc)
        mutation(invalid)
        with pytest.raises(KimFormatError):
            write_document(tmp_path / 'invalid.kima', 'assembly', invalid, overwrite=False)
