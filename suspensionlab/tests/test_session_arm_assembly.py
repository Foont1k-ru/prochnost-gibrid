"""Сеансовая ссылка — не постоянная связь проекта и не изменение файлов."""
from copy import deepcopy

import pytest

from suspensionlab.model.kim_format import KimFormatError, write_document
from suspensionlab.model.scheme_arm_assembly import make_scheme_arm_assembly
from suspensionlab.model.session_arm_assembly import SessionArmAssembly
from suspensionlab.model.templates import load_template


def document(project):
    return make_scheme_arm_assembly(project, 12, 2, {'axis': 'x', 'outer_radius_mm': 14,
                                                    'bore_radius_mm': 7, 'length_mm': 24})


def test_saved_session_link_matches_only_same_project_and_warns_about_source_changes(tmp_path):
    project = load_template('ring')
    doc = document(project)
    path = tmp_path / 'сборка.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    original = path.read_bytes()
    before = deepcopy(project.to_dict())
    link = SessionArmAssembly.from_saved(project, path, doc)
    assert link.source_matches(project) and link.load_verified(project) == doc
    assert project.to_dict() == before and path.read_bytes() == original
    other_project = load_template('ring')
    assert other_project.to_dict() == before and not link.source_matches(other_project)
    with pytest.raises(KimFormatError):
        link.load_verified(other_project)
    point = project.front.hardpoints['lbj']
    point.z += 1
    assert not link.source_matches(project) and link.load_verified(project) == doc
    assert path.read_bytes() == original
    point.z -= 1
    assert link.source_matches(project)
    project.vehicle.mass_kg += 10
    assert link.source_matches(project)  # Only type and three points are compared.
    del project.front.hardpoints['lbj']
    assert not link.source_matches(project)


def test_file_changed_deleted_or_wrong_document_never_opened_or_overwritten(tmp_path):
    project = load_template('city')
    doc = document(project)
    path = tmp_path / 'arm.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    altered = deepcopy(doc)
    altered['name'] = 'Другая сборка'
    with pytest.raises(KimFormatError):
        SessionArmAssembly.from_saved(project, path, altered)
    link = SessionArmAssembly.from_saved(project, path, doc)
    doc['name'] = 'Внешнее изменение словаря'
    assert link.saved_document['name'] != doc['name']
    write_document(path, 'assembly', altered, overwrite=True)
    changed = path.read_bytes()
    with pytest.raises(KimFormatError):
        link.load_verified(project)
    assert path.read_bytes() == changed
    path.unlink()
    with pytest.raises(KimFormatError):
        link.load_verified(project)
