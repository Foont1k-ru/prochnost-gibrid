"""Общая геометрия одного управляемого пространственного изгиба."""
import math
from copy import deepcopy

import pytest

from suspensionlab.model.bent_tube import BentTubeError, make_bend_path
from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document
from suspensionlab.model.welded_arm import (
    make_welded_arm,
    preview_rebuild_welded_arm,
    rebuild_welded_arm,
    validate_welded_arm,
    weldment_centerlines,
)


def project():
    p = Project.create_default()
    for code, xyz in {'lca_f_in': (0., 0., 0.), 'lca_r_in': (0., -100., 0.), 'lbj': (100., 100., 0.)}.items():
        pt = p.front.hardpoints[code]
        pt.x, pt.y, pt.z = xyz
    return p


def test_quarter_circle_geometry_is_tangent_and_sampled():
    path = make_bend_path((0, 0, 0), (100, 0, 0), (100, 100, 0), 20, 10)
    assert path.tangent_start == pytest.approx((80, 0, 0))
    assert path.tangent_end == pytest.approx((100, 20, 0))
    assert path.center == pytest.approx((80, 20, 0))
    assert path.midpoint == pytest.approx((80 + 20 / math.sqrt(2), 20 - 20 / math.sqrt(2), 0))
    assert path.length == pytest.approx(160 + 10 * math.pi)
    sample = path.sample()
    assert sample[0] == (0, 0, 0) and sample[-1] == (100, 100, 0)
    assert sample[1] == pytest.approx(path.tangent_start) and sample[-2] == pytest.approx(path.tangent_end)
    assert all(math.dist(point, path.center) == pytest.approx(20) for point in sample[1:-1])


def test_space_rotation_and_translation_do_not_change_length():
    path = make_bend_path((4, 5, 6), (4, 105, 6), (4, 105, 106), 20, 10)
    assert path.tangent_start == pytest.approx((4, 85, 6))
    assert path.tangent_end == pytest.approx((4, 105, 26))
    assert path.length == pytest.approx(160 + 10 * math.pi)
    assert all(p[0] == pytest.approx(4) for p in path.sample())


@pytest.mark.parametrize('start,vertex,end,radius,tube', [
    ((0, 0, 0), (0, 0, 0), (10, 10, 0), 2, 1),
    ((0, 0, 0), (1, 0, 0), (2, 0, 0), 2, 1),
    ((0, 0, 0), (1, 0, 0), (0.5, 0, 0), 2, 1),
    ((0, 0, 0), (10, 0, 0), (10, 10, 0), 20, 1),
    ((0, 0, 0), (100, 0, 0), (100, 100, 0), 10, 10),
    ((0, 0, 0), (100, float('nan'), 0), (100, 100, 0), 20, 10),
    ((0, 0, 0), (100, 0, 0), (100, 100, 0), True, 10),
    ((0, 0, 0), (100, 0, 0), (100, 100, 0), -20, 10),
])
def test_invalid_or_impossible_bends_are_rejected(start, vertex, end, radius, tube):
    with pytest.raises(BentTubeError):
        make_bend_path(start, vertex, end, radius, tube)


def test_bent_weldment_roundtrip_rebuild_and_copy_safety(tmp_path):
    p = project()
    spec = {'front': {'vertex_mm': [100., 0., 0.], 'radius_mm': 20.}}
    doc = make_welded_arm(p, 10, 2, 'unknown', bends=spec)
    assert doc['version'] == '0.3'
    assert doc['parts'][0]['version'] == '0.2'
    assert doc['parts'][1]['version'] == '0.1'
    spec['front']['vertex_mm'][0] = 500  # snapshot does not share caller's list
    assert doc['parts'][0]['geometry']['bend_vertex_mm'] == [100, 0, 0]
    path = tmp_path / 'bent.kima'
    write_document(path, 'assembly', doc)
    before = path.read_bytes()
    saved = read_document(path, 'assembly')
    assert saved == doc and len(weldment_centerlines(saved)[0]) > 3
    part_path = tmp_path / 'tube.kim'
    write_document(part_path, 'part', saved['parts'][0])
    assert read_document(part_path, 'part') == saved['parts'][0]
    p.front.hardpoints['lbj'].y = 140
    candidate, matches = preview_rebuild_welded_arm(saved, p)
    assert not matches and candidate['parts'][0]['geometry']['bend_vertex_mm'] == [100, 0, 0]
    assert candidate['parts'][0]['geometry']['bend_radius_mm'] == 20
    assert path.read_bytes() == before and saved == doc
    p.front.hardpoints['lbj'].y = 10  # fixed vertex and radius no longer fit
    with pytest.raises(KimFormatError):
        rebuild_welded_arm(saved, p)
    assert path.read_bytes() == before


def test_both_tubes_independent_and_version_strict():
    p = project()
    bends = {'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
             'rear': {'vertex_mm': [100, -100, 0], 'radius_mm': 30}}
    doc = make_welded_arm(p, 10, 2, 'required', bends=bends)
    assert all(part['geometry']['kind'] == 'prototype_arm_bent_tube' for part in doc['parts'])
    broken = deepcopy(doc)
    broken['version'] = '0.2'
    with pytest.raises(KimFormatError):
        validate_welded_arm(broken)
    straight = make_welded_arm(p, 10, 2, 'unknown')
    assert straight['version'] == '0.2'
    straight['version'] = '0.3'
    with pytest.raises(KimFormatError):
        validate_welded_arm(straight)


def test_unknown_and_wrong_versions_never_overwrite_existing_file(tmp_path):
    p = project()
    bends = {'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20}}
    doc = make_welded_arm(p, 10, 2, 'unknown', bends=bends)
    path = tmp_path / 'arm.kima'
    write_document(path, 'assembly', doc)
    before = path.read_bytes()
    for mutation in (
        lambda d: d['parts'][0]['geometry'].update(bend_radius_mm=1),
        lambda d: d['parts'][0]['geometry'].update(unknown='future'),
        lambda d: d['parts'][0].update(version='0.1'),
        lambda d: d['parts'][0]['geometry'].update(bend_vertex_mm=[100, 0]),
    ):
        broken = deepcopy(doc)
        mutation(broken)
        with pytest.raises(KimFormatError):
            write_document(path, 'assembly', broken)
        assert path.read_bytes() == before


def test_explicit_edit_and_remove_bends_preserve_original_and_part_names():
    from suspensionlab.model.welded_arm import weldment_bends

    p = project()
    doc = make_welded_arm(p, 10, 2, 'required', bends={
        'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
    })
    doc['name'] = 'Сборка А'
    doc['parts'][0]['name'] = 'Моя труба'
    original = deepcopy(doc)
    edits = weldment_bends(doc)
    edits['front']['radius_mm'] = 25
    changed, matches = preview_rebuild_welded_arm(doc, p, bends=edits)
    assert matches and changed['version'] == '0.3'
    assert changed['parts'][0]['geometry']['bend_radius_mm'] == 25
    assert changed['name'] == 'Сборка А' and changed['parts'][0]['name'] == 'Моя труба'
    assert doc == original
    removed = rebuild_welded_arm(doc, p, bends={})
    assert removed['version'] == '0.2' and removed['parts'][0]['version'] == '0.1'
    assert removed['parts'][0]['name'] == 'Моя труба' and doc == original
    added = rebuild_welded_arm(removed, p, bends=edits)
    assert added == changed and removed['version'] == '0.2'
    edits['front']['radius_mm'] = 1000
    with pytest.raises(KimFormatError):
        preview_rebuild_welded_arm(doc, p, bends=edits)
    assert doc == original


def test_weldment_bends_returns_independent_coordinates():
    from suspensionlab.model.welded_arm import weldment_bends

    p = project()
    doc = make_welded_arm(p, 10, 2, 'unknown', bends={
        'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
    })
    copied = weldment_bends(doc)
    copied['front']['vertex_mm'][0] = -999
    assert doc['parts'][0]['geometry']['bend_vertex_mm'] == [100, 0, 0]
