"""Сохранённое правило пары не содержит внешних ссылок или независимых копий."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import KimFormatError, inspect_assembly_arm_sources, read_document, write_document
from suspensionlab.model.rear_pair_snapshot import make_rear_pair_snapshot, rear_pair_sides, validate_rear_pair_snapshot
from suspensionlab.model.rear_tube import make_rear_tube


def source():
    p = Project.create_default()
    p.rear.type_code, p.rear.layout = 'live_axle_coil', '4link_panhard'
    p.rear.ensure_points(overwrite=True)
    for code, xyz in {'ll_in_l': (0, 0, 0), 'll_out_l': (100, 100, 0),
                      'll_in_r': (0, 0, 0), 'll_out_r': (100, -100, 0)}.items():
        point = p.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    return make_rear_tube(p, 'rear_lower_left', 10, 2, {'vertex_mm': [100, 0, 0], 'radius_mm': 20})


@pytest.mark.parametrize('mode,roll', [('same', 70), ('mirror', 0)])
def test_pair_roundtrip_and_dynamic_derivation(tmp_path, mode, roll):
    base = source()
    saved = make_rear_pair_snapshot(base, mode, roll)
    path = tmp_path / 'pair.kima'
    write_document(path, 'assembly', saved, overwrite=False)
    reloaded = read_document(path, 'assembly')
    left, right = rear_pair_sides(reloaded)
    assert reloaded == saved and left == base and right['arm'] == 'rear_lower_right'
    left['radius_mm'] = 11
    assert reloaded == saved and base['radius_mm'] == 10
    updated = make_rear_pair_snapshot(left, mode, roll)
    assert rear_pair_sides(updated)[1]['radius_mm'] == 11
    assert path.read_bytes() and read_document(path, 'assembly') == saved
    with pytest.raises(KimFormatError):
        inspect_assembly_arm_sources(saved)


def test_strict_contents_and_incompatible_geometry_rejected():
    doc = make_rear_pair_snapshot(source(), 'same')
    mutations = [lambda d: d.update(version='0.7'), lambda d: d.update(algorithm='rear-pair-v2'),
                 lambda d: d.update(mode=[]), lambda d: d.update(roll_degrees=True),
                 lambda d: d.update(roll_degrees=float('nan')), lambda d: d.update(extra='file.step'),
                 lambda d: d['source'].update(arm='panhard'),
                 lambda d: d['source']['scheme']['rear_axle']['hardpoints']['ll_out_r'].update(y=-120)]
    for mutate in mutations:
        broken = deepcopy(doc)
        mutate(broken)
        with pytest.raises(KimFormatError):
            validate_rear_pair_snapshot(broken)
    with pytest.raises(KimFormatError):
        make_rear_pair_snapshot(source(), 'mirror', 10)
