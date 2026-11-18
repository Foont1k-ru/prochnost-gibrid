"""Исследовательский формат KIM не является полноценным CAD-редактором."""

import json
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import (
    KimFormatError,
    make_assembly,
    make_test_cylinder,
    read_document,
    write_document,
)
from suspensionlab.model.project_io import load_project, save_project


def prototype():
    part = make_test_cylinder('lower_front', 'Пробная деталь: нижний передний рычаг', 12.5, 200.)
    instances = [
        {'id': 'left', 'part_id': 'lower_front', 'translation_mm': [10., 20., 30.]},
        {'id': 'right', 'part_id': 'lower_front', 'translation_mm': [10., -20., 30.]},
    ]
    project = Project.create_default()
    project.meta.name = 'Нива 21214 — схема'
    project.vehicle.mass_kg = 1777.
    project.add_snapshot('Исходная схема')
    return part, make_assembly('Подвеска', [part], instances, project), project


def test_cyrillic_part_and_self_contained_assembly_roundtrip(tmp_path):
    part, assembly, project = prototype()
    part_file = tmp_path / 'рычаг нижний передний.kim'
    assembly_file = tmp_path / 'подвеска.kima'
    write_document(part_file, 'part', part)
    write_document(assembly_file, 'assembly', assembly)
    assert read_document(part_file, 'part') == part
    assert read_document(assembly_file, 'assembly') == assembly
    assert assembly['scheme'] == project.to_dict()
    part_file.unlink()  # Embedded document, no external dependency.
    assert read_document(assembly_file, 'assembly')['parts'][0] == part
    assert assembly['frame'] == 'unregistered'


def test_scheme_import_from_existing_file_is_non_destructive(tmp_path):
    project = Project.create_default()
    source = save_project(project, tmp_path / 'старый проект')
    original = source.read_bytes()
    loaded = load_project(source)
    assembly = make_assembly('Перенос схемы', [], [], loaded)
    write_document(tmp_path / 'проект.kima', 'assembly', assembly)
    assert read_document(tmp_path / 'проект.kima', 'assembly')['scheme'] == loaded.to_dict()
    assert source.read_bytes() == original
    assert loaded.path == str(source)


def test_assembly_makes_an_independent_snapshot():
    part, assembly, project = prototype()
    part['geometry']['radius_mm'] = 50.
    project.vehicle.mass_kg = 999.
    assert assembly['parts'][0]['geometry']['radius_mm'] == 12.5
    assert assembly['scheme']['vehicle']['mass_kg'] == 1777.


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), True, '3', 1e7])
def test_cylinder_dimensions_are_strict_and_bounded(value):
    with pytest.raises(KimFormatError):
        make_test_cylinder('a', 'Тест', value, 10.)


@pytest.mark.parametrize('mutate', [
    lambda a: a.update(version='99'),
    lambda a: a.update(extra='unknown future field'),
    lambda a: a.update(units='inches'),
    lambda a: a.update(frame='car'),
    lambda a: a['parts'][0].update(version='99'),
    lambda a: a['parts'][0]['geometry'].update(kind='script'),
    lambda a: a['parts'].append(deepcopy(a['parts'][0])),
    lambda a: a['instances'].append(deepcopy(a['instances'][0])),
    lambda a: a['instances'][0].update(part_id='missing'),
    lambda a: a['instances'][0].update(translation_mm=[1., 2.]),
    lambda a: a['instances'][0].update(translation_mm=[1., 2., float('inf')]),
    lambda a: a['instances'][0].update(rotation=[0, 0, 0]),
    lambda a: a['scheme'].update(extra='unknown'),
    lambda a: a['scheme'].pop('vehicle'),
])
def test_reject_unknown_or_inconsistent_data_without_replacing_file(tmp_path, mutate):
    _, assembly, _ = prototype()
    path = tmp_path / 'подвеска.kima'
    write_document(path, 'assembly', assembly)
    before = path.read_bytes()
    bad = deepcopy(assembly)
    mutate(bad)
    with pytest.raises(KimFormatError):
        write_document(path, 'assembly', bad)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('content', [
    '{"format":"kim-part","format":"kima-assembly"}',
    '{"geometry":{"x":NaN}}',
    '{"geometry":{"x":1e999}}',
    '{"a":' + '[' * 3000 + '0' + ']' * 3000 + '}',
    'not json',
])
def test_malformed_and_untrusted_json_is_rejected(tmp_path, content):
    path = tmp_path / 'data.kim'
    path.write_text(content, encoding='utf-8')
    with pytest.raises(KimFormatError):
        read_document(path, 'part')
    assert path.read_text(encoding='utf-8') == content


def test_suffix_mismatch_never_overwrites_user_project(tmp_path):
    part, assembly, _ = prototype()
    old = tmp_path / 'old.susp.json'
    old.write_bytes(b'important')
    for document, kind in [(part, 'part'), (assembly, 'assembly')]:
        with pytest.raises(KimFormatError):
            write_document(old, kind, document)
    with pytest.raises(KimFormatError):
        write_document(tmp_path / 'wrong.kim', 'assembly', assembly)
    assert old.read_bytes() == b'important'


def test_atomic_write_error_preserves_previous_and_removes_temp(tmp_path, monkeypatch):
    from suspensionlab.model import kim_format

    part, _, _ = prototype()
    path = tmp_path / 'деталь.kim'
    write_document(path, 'part', part)
    old = path.read_bytes()
    def fail(*args):
        raise OSError('simulated failed replacement')
    monkeypatch.setattr(kim_format.os, 'replace', fail)
    part['geometry']['radius_mm'] = 13.
    with pytest.raises(KimFormatError):
        write_document(path, 'part', part)
    assert path.read_bytes() == old and list(tmp_path.iterdir()) == [path]


def test_versioned_unknown_fields_cannot_be_silently_discarded_on_read(tmp_path):
    part, _, _ = prototype()
    part['future'] = {'important': 1}
    path = tmp_path / 'future.kim'
    text = json.dumps(part)
    path.write_text(text, encoding='utf-8')
    with pytest.raises(KimFormatError):
        read_document(path, 'part')
    assert path.read_text(encoding='utf-8') == text


def test_refuses_symlink_destination_even_if_it_points_to_project(tmp_path):
    part, _, _ = prototype()
    old = tmp_path / 'user-project.susp.json'
    old.write_bytes(b'important')
    alias = tmp_path / 'part.kim'
    try:
        alias.symlink_to(old)
    except OSError:
        pytest.skip('Creating symlinks is unavailable')
    with pytest.raises(KimFormatError):
        write_document(alias, 'part', part)
    assert old.read_bytes() == b'important' and alias.is_symlink()
