"""Снимки передних труб; проект и ранее созданные файлы не изменяются."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.front_tube_arm import (
    front_tube_arm_centerlines,
    front_tube_arm_points,
    make_front_tube_arm,
    validate_front_tube_arm,
)
from suspensionlab.model.kim_format import KimFormatError, inspect_assembly_arm_sources, read_document, write_document
from suspensionlab.model.niva_arm_views import FRONT


def project():
    p = Project.create_default()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (0, -100, 0), 'ubj': (100, 100, 0),
                      'lca_f_in': (0, 0, 0), 'lca_r_in': (0, -100, 0), 'lbj': (100, 100, 0)}.items():
        point = p.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    return p


def test_all_four_arms_individual_bends_and_roundtrip(tmp_path):
    p = project()
    initial = p.to_dict()
    for key in FRONT:
        straight = make_front_tube_arm(p, key, 10, 2)
        assert straight['version'] == '0.5' and all(len(path) == 2 for path in front_tube_arm_centerlines(straight))
        sign = -1 if key.endswith('_right') else 1
        bends = {'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
                 'rear': {'vertex_mm': [100, -100*sign, 0], 'radius_mm': 25}}
        curved = make_front_tube_arm(p, key, 10, 2, bends)
        assert all(len(path) > 3 for path in front_tube_arm_centerlines(curved))
        bends['front']['vertex_mm'][0] = -1
        assert curved['bends']['front']['vertex_mm'][0] == 100
        path = tmp_path / (key + '.kima')
        write_document(path, 'assembly', curved, overwrite=False)
        assert read_document(path, 'assembly') == curved
        old = path.read_bytes()
        with pytest.raises(KimFormatError):
            write_document(path, 'assembly', straight, overwrite=False)
        assert path.read_bytes() == old
    left = make_front_tube_arm(p, 'front_upper_left', 10, 2)
    right = make_front_tube_arm(p, 'front_upper_right', 10, 2)
    assert front_tube_arm_points(right) == tuple((x, -y, z) for x, y, z in front_tube_arm_points(left))
    assert p.to_dict() == initial
    with pytest.raises(KimFormatError):
        inspect_assembly_arm_sources(left)  # unrelated legacy inspector, not a fake match


def test_strict_validation_and_wrong_suspension_rejected():
    p = project()
    for radius, wall in ((10, 10), (10, 0), (True, 1), (float('inf'), 1)):
        with pytest.raises(KimFormatError):
            make_front_tube_arm(p, 'front_upper_left', radius, wall)
    for bend in ({'unknown': {'vertex_mm': [100, 0, 0], 'radius_mm': 20}},
                 {'front': {'vertex_mm': [100, 0], 'radius_mm': 20}},
                 {'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 1000}},
                 {'rear': {'vertex_mm': [100, -100, 0], 'radius_mm': float('nan')}}):
        with pytest.raises(KimFormatError):
            make_front_tube_arm(p, 'front_upper_left', 10, 2, bend)
    doc = make_front_tube_arm(p, 'front_upper_left', 10, 2)
    for mutate in (lambda d: d.update(arm=[]), lambda d: d.update(extra=True),
                   lambda d: d.update(frame='rear_axle_snapshot'), lambda d: d.update(scheme=None),
                   lambda d: d['scheme']['front_axle'].update(type='macpherson_front')):
        broken = deepcopy(doc)
        mutate(broken)
        with pytest.raises(KimFormatError):
            validate_front_tube_arm(broken)
    p.front.type_code = 'macpherson_front'
    with pytest.raises(KimFormatError):
        make_front_tube_arm(p, 'front_upper_left', 10, 2)


def test_snapshot_does_not_change_with_project():
    p = project()
    old = make_front_tube_arm(p, 'front_lower_right', 10, 2)
    saved = deepcopy(old)
    p.front.hardpoints['lbj'].y += 10
    assert make_front_tube_arm(p, 'front_lower_right', 10, 2) != old and old == saved
