"""Самодостаточная условная компоновка задней пары и выбранной оси втулок."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.joint_concept import DEFAULTS, make_joint_concept
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document
from suspensionlab.model.rear_joint_layout import make_rear_joint_layout
from suspensionlab.model.rear_pair_snapshot import make_rear_pair_snapshot
from suspensionlab.model.rear_tube import make_rear_tube


def project():
    p = Project.create_default()
    p.rear.type_code, p.rear.layout = 'live_axle_coil', '4link_panhard'
    p.rear.ensure_points(overwrite=True)
    for code, xyz in {'ll_in_l': (0, 10, 0), 'll_out_l': (100, 110, 0),
                      'll_in_r': (0, -10, 0), 'll_out_r': (100, -110, 0),
                      'ul_in_l': (0, 20, 5), 'ul_out_l': (100, 120, 5),
                      'ul_in_r': (0, -20, 5), 'ul_out_r': (100, -120, 5)}.items():
        pt = p.rear.hardpoints[code]
        pt.x, pt.y, pt.z = xyz
    return p


@pytest.mark.parametrize('arm', ['rear_upper_left', 'rear_upper_right', 'rear_lower_left', 'rear_lower_right'])
@pytest.mark.parametrize('mode', ['same', 'mirror'])
def test_snapshots_for_each_side_and_pair_rule(tmp_path, arm, mode):
    p = project()
    before = p.to_dict()
    tube = make_rear_tube(p, arm, 10, 2)
    pair = make_rear_pair_snapshot(tube, mode)
    bush = make_joint_concept('bushing', DEFAULTS['bushing'])
    doc = make_rear_joint_layout(pair, bush, 'x')
    path = tmp_path / f'{arm}-{mode}.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    bush['parameters']['body_length_mm'] = 27
    assert read_document(path, 'assembly') == doc and doc['bushing'] != bush and p.to_dict() == before


def test_strict_embedded_types_axis_and_incompatible_geometry(tmp_path):
    tube = make_rear_tube(project(), 'rear_lower_left', 10, 2)
    pair = make_rear_pair_snapshot(tube, 'same')
    bush = make_joint_concept('bushing', DEFAULTS['bushing'])
    doc = make_rear_joint_layout(pair, bush, 'y')
    mutations = [lambda d: d.update(axis=[]), lambda d: d.update(axis='diagonal'),
                 lambda d: d.update(external='component.step'), lambda d: d.update(algorithm='future'),
                 lambda d: d.update(bushing=make_joint_concept('ball', DEFAULTS['ball'])),
                 lambda d: d['pair'].update(mode='invalid')]
    for mutate in mutations:
        bad = deepcopy(doc)
        mutate(bad)
        with pytest.raises(KimFormatError):
            write_document(tmp_path / 'bad.kima', 'assembly', bad, overwrite=False)
