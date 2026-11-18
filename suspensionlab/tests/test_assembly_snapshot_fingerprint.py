"""Информационный код сравнения снимков сборки, без изменения .kima/.kim."""
import hashlib
import json
from copy import deepcopy

import pytest

from suspensionlab.model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint
from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import KimFormatError, read_document, write_document
from suspensionlab.model.scheme_arm_assembly import (
    edit_assembly_part,
    make_plate,
    make_scheme_arm_assembly,
    rebuild_scheme_arm_assembly,
    set_assembly_axis,
    set_assembly_plate,
)


def document():
    project = Project.create_default()
    project.meta.created = '2024-01-01'
    return make_scheme_arm_assembly(project, 12, 2,
                                    {'axis': 'x', 'outer_radius_mm': 14, 'bore_radius_mm': 7, 'length_mm': 24})


def test_v1_stable_and_normalizes_dictionary_order_and_equal_numbers(tmp_path):
    doc = document()
    frozen = deepcopy(doc)
    fingerprint = assembly_snapshot_fingerprint(doc)
    assert fingerprint == 'ab1d6156191fccc228cbe9a8cd4233f1e7fd103e58d4b18df2e794afd82b875d'
    reordered = json.loads(json.dumps(doc, sort_keys=True, ensure_ascii=True))
    reordered['parts'][0]['geometry']['radius_mm'] = 12.0
    reordered['parts'][0]['geometry']['wall_mm'] = 2.0
    assert assembly_snapshot_fingerprint(reordered) == fingerprint
    path = tmp_path / 'сборка.kima'
    write_document(path, 'assembly', doc, overwrite=False)
    assert assembly_snapshot_fingerprint(read_document(path, 'assembly')) == fingerprint
    assert hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint
    assert doc == frozen


def test_changed_dimensions_axis_plate_name_or_scheme_change_code():
    doc = document()
    original = assembly_snapshot_fingerprint(doc)
    changed_radius = edit_assembly_part(doc, 'tube_front', {'radius_mm': 13, 'wall_mm': 2})
    changed_axis = set_assembly_axis(doc, 'y')
    changed_plate = set_assembly_plate(doc, make_plate(40, 20, 3, 5),
                                       {'normal': 'z', 'offset_mm': [0, 0, 0]})
    changed_name = deepcopy(doc)
    changed_name['name'] = 'Другое имя'
    project = Project.from_dict(doc['scheme'])
    project.meta.comment = 'Изменена метка проекта'
    changed_scheme = rebuild_scheme_arm_assembly(doc, project)
    assert all(assembly_snapshot_fingerprint(candidate) != original for candidate in
               (changed_radius, changed_axis, changed_plate, changed_name, changed_scheme))
    assert assembly_snapshot_fingerprint(doc) == original


def test_boolean_and_equal_number_are_not_conflated():
    doc = document()
    altered = deepcopy(doc)
    # The project parser currently accepts 1 for a boolean because Python
    # equality equates them. A fingerprint still detects the representation.
    altered['scheme']['front_axle']['arb']['enabled'] = 1
    assert doc == altered
    assert assembly_snapshot_fingerprint(doc) != assembly_snapshot_fingerprint(altered)


def test_invalid_document_is_not_fingerprinted():
    doc = document()
    doc['parts'][0]['geometry']['radius_mm'] = -1
    with pytest.raises(KimFormatError):
        assembly_snapshot_fingerprint(doc)
