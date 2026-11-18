"""Самодостаточная сборка и отдельные KIM-детали без неявной потери данных."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document
from suspensionlab.model.scheme_arm_assembly import (
    make_scheme_arm_assembly,
    rebuild_scheme_arm_assembly,
)


def parameters():
    return {'axis': 'x', 'outer_radius_mm': 14., 'bore_radius_mm': 7., 'length_mm': 24.}


def test_assembly_contains_four_independent_embedded_parts_and_rebuilds_safely(tmp_path):
    project = Project.create_default()
    doc = make_scheme_arm_assembly(project, 12, 2, parameters())
    original = deepcopy(doc)
    assert doc['version'] == '0.15' and len(doc['parts']) == 4
    path = tmp_path / 'assembly.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    for index, part in enumerate(doc['parts']):
        part_path = tmp_path / f'{index}.kim'
        write_document(part_path, 'part', part, overwrite=False)
        assert read_document(part_path, 'part') == part
    project.front.hardpoints['lca_f_in'].x += 20
    updated = rebuild_scheme_arm_assembly(doc, project)
    assert updated['parts'][:2] != original['parts'][:2]
    assert updated['parts'][2:] == original['parts'][2:] and updated['axis'] == 'x'
    assert doc == original and read_document(path, 'assembly') == original
    assert updated['scheme'] == project.to_dict()
    project.front.type_code = 'macpherson_front'
    with pytest.raises(KimFormatError):
        rebuild_scheme_arm_assembly(doc, project)
    assert doc == original


@pytest.mark.parametrize('mutate', [
    lambda d: d.update(axis='tube'), lambda d: d.update(algorithm='future'),
    lambda d: d.update(unresolved=[]), lambda d: d.update(extra='manual_model'),
    lambda d: d['parts'][0].update(id='housing_front'), lambda d: d['parts'].pop(),
    lambda d: d['parts'][0]['geometry']['source']['coordinates_mm'][0].__setitem__(0, 99999),
    lambda d: d['parts'][2]['geometry'].update(bore_radius_mm=14),
    lambda d: d['parts'][2]['geometry'].update(manual_operations=['hole']),
])
def test_reject_unknown_or_inconsistent_data_without_overwriting(tmp_path, mutate):
    doc = make_scheme_arm_assembly(Project.create_default(), 12, 2, parameters())
    path = tmp_path / 'original.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    before = path.read_bytes()
    broken = deepcopy(doc)
    mutate(broken)
    with pytest.raises(KimFormatError):
        write_document(path, 'assembly', broken)
    with pytest.raises(KimFormatError):
        rebuild_scheme_arm_assembly(broken, Project.create_default())
    assert path.read_bytes() == before


def test_rebuild_preserves_individual_dimensions_and_names():
    project = Project.create_default()
    doc = make_scheme_arm_assembly(project, 12, 2, parameters())
    doc['parts'][1]['geometry']['radius_mm'] = 15
    doc['parts'][2]['geometry']['length_mm'] = 30
    doc['parts'][0]['name'] = 'Индивидуальная труба'
    project.front.hardpoints['lbj'].y += 10
    updated = rebuild_scheme_arm_assembly(doc, project)
    assert updated['parts'][1]['geometry']['radius_mm'] == 15
    assert updated['parts'][2]['geometry']['length_mm'] == 30
    assert updated['parts'][0]['name'] == 'Индивидуальная труба'


def test_edit_each_part_axis_and_rebuild_preserve_all_changes_and_deep_copy(tmp_path):
    from suspensionlab.model.scheme_arm_assembly import edit_assembly_part, set_assembly_axis

    project = Project.create_default()
    original = make_scheme_arm_assembly(project, 12, 2, parameters())
    doc = edit_assembly_part(original, 'tube_front', {'radius_mm': 15.25, 'wall_mm': 3.25})
    doc = edit_assembly_part(doc, 'tube_rear', {'radius_mm': 18, 'wall_mm': 4})
    doc = edit_assembly_part(doc, 'housing_front', {'outer_radius_mm': 18, 'bore_radius_mm': 8, 'length_mm': 32})
    doc = edit_assembly_part(doc, 'housing_rear', {'outer_radius_mm': 21, 'bore_radius_mm': 9, 'length_mm': 28})
    doc = set_assembly_axis(doc, 'z')
    assert original['axis'] == 'x' and original['parts'][0]['geometry']['radius_mm'] == 12
    assert doc['parts'][0]['geometry']['radius_mm'] == 15.25
    path = tmp_path / 'edited.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    frozen = deepcopy(doc)
    project.front.hardpoints['lca_f_in'].x += 30
    updated = rebuild_scheme_arm_assembly(doc, project)
    for old, new in zip(frozen['parts'], updated['parts'], strict=True):
        old_geometry, new_geometry = deepcopy(old['geometry']), deepcopy(new['geometry'])
        old_geometry.pop('source', None)
        new_geometry.pop('source', None)
        assert new_geometry == old_geometry and new['name'] == old['name']
    assert updated['axis'] == 'z' and doc == frozen and read_document(path, 'assembly') == frozen


@pytest.mark.parametrize('identifier,dimensions', [
    ('tube_front', {'radius_mm': 5, 'wall_mm': 5}),
    ('tube_rear', {'radius_mm': float('nan'), 'wall_mm': 2}),
    ('tube_front', {'radius_mm': 12, 'wall_mm': 2, 'extra': 3}),
    ('housing_rear', {'outer_radius_mm': 7, 'bore_radius_mm': 7, 'length_mm': 24}),
    ('housing_front', {'outer_radius_mm': 15, 'bore_radius_mm': 7, 'length_mm': -1}),
    ('unknown', {'radius_mm': 12, 'wall_mm': 2}),
])
def test_invalid_edits_never_change_original(identifier, dimensions):
    from suspensionlab.model.scheme_arm_assembly import edit_assembly_part

    original = make_scheme_arm_assembly(Project.create_default(), 12, 2, parameters())
    before = deepcopy(original)
    with pytest.raises(KimFormatError):
        edit_assembly_part(original, identifier, dimensions)
    assert original == before


def test_replace_part_is_explicit_and_rejects_conflicts():
    from suspensionlab.model.scheme_arm_assembly import replace_assembly_part, set_assembly_axis

    project = Project.create_default()
    doc = make_scheme_arm_assembly(project, 12, 2, parameters())
    before = deepcopy(doc)
    imported = deepcopy(doc['parts'][3])
    imported['name'] = 'Другая втулка'
    imported['geometry']['length_mm'] = 35
    result = replace_assembly_part(doc, 'housing_front', imported)
    assert result['parts'][2]['id'] == 'housing_front' and result['parts'][2]['name'] == 'Другая втулка'
    assert result['parts'][2]['geometry']['length_mm'] == 35 and imported['id'] == 'housing_rear'
    assert result['parts'][3] == before['parts'][3] and doc == before
    with pytest.raises(KimFormatError):
        replace_assembly_part(doc, 'tube_front', doc['parts'][1])
    stale = deepcopy(doc['parts'][0])
    stale['geometry']['source']['coordinates_mm'][0][0] += 2
    with pytest.raises(KimFormatError):
        replace_assembly_part(doc, 'tube_front', stale)
    with pytest.raises(KimFormatError):
        replace_assembly_part(doc, 'housing_front', doc['parts'][0])
    with pytest.raises(KimFormatError):
        set_assembly_axis(doc, 'tube')
    assert doc == before
