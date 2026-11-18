"""Зеркало создаётся по сохранённому исходнику, без изменения проекта и копий."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.front_pair_snapshot import front_pair_sides, make_front_pair_snapshot, mirror_front_tube_arm
from suspensionlab.model.front_tube_arm import front_tube_arm_centerlines, make_front_tube_arm
from suspensionlab.model.kim_format import KimFormatError, inspect_assembly_arm_sources, read_document, write_document
from suspensionlab.model.niva_arm_views import FRONT


def project():
    p = Project.create_default()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (0, -100, 0), 'ubj': (100, 100, 0),
                      'lca_f_in': (0, 0, 0), 'lca_r_in': (0, -100, 0), 'lbj': (100, 100, 0)}.items():
        pt = p.front.hardpoints[code]
        pt.x, pt.y, pt.z = xyz
    return p


@pytest.mark.parametrize('arm', FRONT)
def test_mirrored_pair_round_trip_and_live_update(tmp_path, arm):
    p = project()
    before = p.to_dict()
    sign = -1 if arm.endswith('right') else 1
    bends = {'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
             'rear': {'vertex_mm': [100, -100*sign, 0], 'radius_mm': 25}}
    source = make_front_tube_arm(p, arm, 10, 2, bends)
    pair = make_front_pair_snapshot(source)
    name = tmp_path / f'{arm}.kima'
    write_document(name, 'assembly', pair, overwrite=False)
    old = name.read_bytes()
    original, mirror = front_pair_sides(read_document(name, 'assembly'))
    assert original == source and mirror['arm'] != source['arm']
    for path, mirrored_path in zip(front_tube_arm_centerlines(original), front_tube_arm_centerlines(mirror), strict=True):
        for (x, y, z), (mx, my, mz) in zip(path, mirrored_path, strict=True):
            assert (mx, my, mz) == pytest.approx((x, -y, z))
    assert mirror_front_tube_arm(mirror) == source
    original['radius_mm'] = 11
    updated = make_front_pair_snapshot(original)
    assert front_pair_sides(updated)[1]['radius_mm'] == 11
    assert name.read_bytes() == old and p.to_dict() == before
    with pytest.raises(KimFormatError):
        inspect_assembly_arm_sources(pair)


def test_strict_version_and_algorithm_no_extra_source_or_external_files(tmp_path):
    source = make_front_tube_arm(project(), 'front_upper_left', 10, 2)
    pair = make_front_pair_snapshot(source)
    mutations = [lambda d: d.update(algorithm='future'), lambda d: d.update(version='0.8'),
                 lambda d: d.update(external='model.step'), lambda d: d.update(source=[]),
                 lambda d: d['source'].update(arm='panhard'),
                 lambda d: d['source'].update(radius_mm=float('nan'))]
    for mutate in mutations:
        invalid = deepcopy(pair)
        mutate(invalid)
        with pytest.raises(KimFormatError):
            write_document(tmp_path / 'invalid.kima', 'assembly', invalid, overwrite=False)
