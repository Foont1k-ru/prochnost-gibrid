"""Связь экспериментального рычага с сохранёнными точками, не проектирование детали."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import (
    KimFormatError,
    compare_lower_arm_source,
    inspect_assembly_arm_sources,
    make_assembly,
    make_lower_arm_prototype,
    read_document,
    write_document,
)


def build():
    project = Project.create_default()
    project.front.hardpoints['lca_f_in'].x = 120.123456
    part = make_lower_arm_prototype('front_lower_left', 'Нижний передний рычаг — черновик', project, 10.)
    return project, part


def test_arm_records_three_named_points_from_serialized_front_left_scheme():
    project, part = build()
    source = part['geometry']['source']
    assert source['axle'] == 'front' and source['side'] == 'left'
    assert source['suspension_type'] == project.front.type_code
    assert source['point_codes'] == ['lca_f_in', 'lca_r_in', 'lbj']
    for code, coord in zip(source['point_codes'], source['coordinates_mm'], strict=True):
        point = project.to_dict()['front_axle']['hardpoints'][code]
        assert coord == [point['x'], point['y'], point['z']]
    assert source['coordinates_mm'][0][0] == 120.1235
    assert compare_lower_arm_source(part, project)


def test_change_detection_uses_only_three_serialized_points_and_type():
    project, part = build()
    initial = deepcopy(part)
    project.vehicle.mass_kg += 100
    project.front.hardpoints['ubj'].x += 1
    assert compare_lower_arm_source(part, project)  # unrelated inputs are not checked
    project.front.hardpoints['lca_f_in'].x += 0.000001
    assert compare_lower_arm_source(part, project)  # serialization rounds to four digits
    project.front.hardpoints['lca_f_in'].x += 2
    assert not compare_lower_arm_source(part, project)
    assert part == initial  # checking never changes either snapshot
    rebuilt = make_lower_arm_prototype('front_lower_left', part['name'], project, 10.)
    assert compare_lower_arm_source(rebuilt, project)
    assert rebuilt['geometry']['source'] != part['geometry']['source']
    project.front.type_code = 'multilink_front'
    assert not compare_lower_arm_source(rebuilt, project)


def test_assembly_and_standalone_roundtrip_keep_captured_coordinates(tmp_path):
    project, part = build()
    standalone = tmp_path / 'рычаг нижний передний.kim'
    container = tmp_path / 'подвеска.kima'
    a = make_assembly('Подвеска', [part], [
        {'id': 'one', 'part_id': 'front_lower_left', 'translation_mm': [0, 0, 0]},
    ], project)
    write_document(standalone, 'part', part)
    write_document(container, 'assembly', a)
    snapshot = read_document(standalone, 'part')
    reopened = read_document(container, 'assembly')
    assert reopened['parts'] == [snapshot] and reopened['scheme'] == project.to_dict()
    assert compare_lower_arm_source(reopened['parts'][0], Project.from_dict(reopened['scheme']))
    project.front.hardpoints['lbj'].y += 12
    assert not compare_lower_arm_source(snapshot, project)
    assert compare_lower_arm_source(reopened['parts'][0], Project.from_dict(reopened['scheme']))


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), 0.001, 'x', True])
def test_prototype_rejects_invalid_radius(value):
    project, _ = build()
    with pytest.raises(KimFormatError):
        make_lower_arm_prototype('arm', 'arm', project, value)


@pytest.mark.parametrize('pair', [('lca_f_in', 'lbj'), ('lca_r_in', 'lbj'), ('lca_f_in', 'lca_r_in')])
def test_prototype_rejects_coincident_points(pair):
    project, _ = build()
    src, dest = (project.front.hardpoints[code] for code in pair)
    src.x, src.y, src.z = dest.x, dest.y, dest.z
    with pytest.raises(KimFormatError):
        make_lower_arm_prototype('arm', 'arm', project, 10)


def test_other_suspensions_missing_points_and_nonfinite_values_are_rejected():
    project, _ = build()
    project.front.type_code = 'multilink_front'
    with pytest.raises(KimFormatError):
        make_lower_arm_prototype('arm', 'arm', project, 10)
    project, _ = build()
    del project.front.hardpoints['lbj']
    with pytest.raises(KimFormatError):
        make_lower_arm_prototype('arm', 'arm', project, 10)
    project, _ = build()
    project.front.hardpoints['lbj'].x = float('inf')
    with pytest.raises(KimFormatError):
        make_lower_arm_prototype('arm', 'arm', project, 10)


@pytest.mark.parametrize('tamper', [
    lambda part: part['geometry']['source'].update(side='right'),
    lambda part: part['geometry']['source'].update(axle='rear'),
    lambda part: part['geometry']['source'].update(suspension_type='unknown'),
    lambda part: part['geometry']['source'].update(point_codes=['lbj', 'lca_r_in', 'lca_f_in']),
    lambda part: part['geometry']['source']['coordinates_mm'][0].__setitem__(1, True),
    lambda part: part['geometry']['source'].update(unknown='data'),
    lambda part: part['geometry'].update(radius_mm=0),
])
def test_invalid_arm_source_will_not_overwrite_file(tmp_path, tamper):
    _, part = build()
    path = tmp_path / 'arm.kim'
    write_document(path, 'part', part)
    before = path.read_bytes()
    tamper(part)
    with pytest.raises(KimFormatError):
        write_document(path, 'part', part)
    assert path.read_bytes() == before


def test_snapshot_audit_distinguishes_match_changed_and_no_scheme():
    project, arm = build()
    instances = [{'id': 'one', 'part_id': arm['id'], 'translation_mm': [0, 0, 0]}]
    saved = make_assembly('Снимок', [arm], instances, project)
    assert inspect_assembly_arm_sources(saved) == {'front_lower_left': 'match'}
    project.front.hardpoints['lbj'].y += 50
    # This checks the saved snapshot, not the live project or placement.
    assert inspect_assembly_arm_sources(saved) == {'front_lower_left': 'match'}
    assert not compare_lower_arm_source(arm, project)
    changed = make_assembly('Изменённая схема', [arm], instances, project)
    assert inspect_assembly_arm_sources(changed) == {'front_lower_left': 'different'}
    detached = make_assembly('Без схемы', [arm], instances)
    assert inspect_assembly_arm_sources(detached) == {'front_lower_left': 'no_scheme'}


def test_macpherson_front_also_supports_named_lower_arm():
    project = Project.create_default()
    project.front.type_code = 'macpherson_front'
    project.front.ensure_points()
    part = make_lower_arm_prototype('arm', 'Макферсон: черновик', project, 10.)
    assert compare_lower_arm_source(part, project)
    assert part['geometry']['source']['suspension_type'] == 'macpherson_front'
