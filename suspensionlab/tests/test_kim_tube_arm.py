"""Параметрические трубы — эксперимент, не спроектированный рычаг."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import (
    KimFormatError,
    compare_lower_arm_source,
    inspect_assembly_arm_sources,
    make_assembly,
    make_lower_arm_tube_prototype,
    read_document,
    rebuild_lower_arm_prototype,
    write_document,
)


def prototype():
    project = Project.create_default()
    part = make_lower_arm_tube_prototype('arm', 'Передний нижний — опытный', project, 12., 2.)
    return project, part


def test_tube_roundtrip_and_explicit_rebuild_preserve_original(tmp_path):
    project, part = prototype()
    original = deepcopy(part)
    path = tmp_path / 'рычаг нижний передний.kim'
    write_document(path, 'part', part)
    loaded = read_document(path, 'part')
    assert loaded == part and compare_lower_arm_source(loaded, project)
    project.front.hardpoints['lbj'].y += 10
    assert not compare_lower_arm_source(loaded, project)
    updated = rebuild_lower_arm_prototype(loaded, project)
    assert compare_lower_arm_source(updated, project)
    assert updated['geometry']['radius_mm'] == 12 and updated['geometry']['wall_mm'] == 2
    assert updated['id'] == part['id'] and updated['name'] == part['name']
    assert loaded == original and read_document(path, 'part') == original
    assembly = make_assembly('Снимок', [updated], [{'id':'i', 'part_id':'arm', 'translation_mm':[0,0,0]}], project)
    assert inspect_assembly_arm_sources(assembly) == {'arm': 'match'}
    assert project.path is None


def test_rebuild_rejects_changed_type_without_mutating_document():
    project, part = prototype()
    original = deepcopy(part)
    project.front.type_code = 'macpherson_front'
    project.front.ensure_points()
    with pytest.raises(KimFormatError):
        rebuild_lower_arm_prototype(part, project)
    assert part == original


@pytest.mark.parametrize('radius,wall', [
    (10, 0), (10, -1), (10, 10), (10, 11), (0, 1), (10, 0.001),
    (10, float('nan')), (float('inf'), 1), (10, True), (10, '2'), (10, 9.9999),
])
def test_invalid_tube_sizes_never_create_part(radius, wall):
    with pytest.raises(KimFormatError):
        make_lower_arm_tube_prototype('arm', 'arm', Project.create_default(), radius, wall)


def test_unknown_source_and_dimensions_do_not_replace_saved_part(tmp_path):
    project, part = prototype()
    path = tmp_path / 'arm.kim'
    write_document(path, 'part', part)
    before = path.read_bytes()
    part['geometry']['wall_mm'] = part['geometry']['radius_mm']
    with pytest.raises(KimFormatError):
        write_document(path, 'part', part)
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]
