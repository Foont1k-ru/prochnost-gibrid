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
