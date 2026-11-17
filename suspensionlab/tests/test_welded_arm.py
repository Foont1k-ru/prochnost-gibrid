"""KIMA 0.2 — неполная схема сборки, не детали для изготовления."""
from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import (
    KimFormatError,
    inspect_assembly_arm_sources,
    make_lower_arm_tube_prototype,
    read_document,
    write_document,
)
from suspensionlab.model.welded_arm import (
    convert_legacy_tubes,
    make_welded_arm,
    rebuild_welded_arm,
    validate_welded_arm,
    weldment_source_matches,
)


def make(damper='unknown'):
    project = Project.create_default()
    return project, make_welded_arm(project, 12., 2., damper)


def test_roundtrip_self_contained_hierarchy_and_unresolved_purchased_items(tmp_path):
    project, doc = make('required')
    path = tmp_path / 'нижний рычаг.kima'
    write_document(path, 'assembly', doc)
    read = read_document(path, 'assembly')
    assert read == doc and read['version'] == '0.2'
    by_id = {node['id']: node for node in read['nodes']}
    assert by_id['weldment']['parent'] == 'arm'
    for ident in ('tube_front', 'tube_rear', 'housing_front', 'housing_rear', 'ball_bracket', 'damper_bracket'):
        assert by_id[ident]['parent'] == 'weldment'
    for ident in ('ball_joint', 'bushing_front', 'bushing_rear', 'fasteners'):
        assert by_id[ident]['parent'] == 'arm' and by_id[ident]['kind'] == 'purchased_unselected'
    assert all(by_id[i]['kind'] == 'unresolved' for i in ('housing_front', 'housing_rear', 'ball_bracket'))
    assert by_id['tube_front']['part_id'] == 'tube_front' and by_id['tube_rear']['part_id'] == 'tube_rear'
    assert [part['geometry']['leg'] for part in read['parts']] == ['front', 'rear']
    assert all(weld['status'] == 'needs_design' for weld in read['welds'])
    assert read['welds'][-1]['a'] == 'damper_bracket' and read['welds'][-1]['b'] is None
    assert weldment_source_matches(read)
    assert inspect_assembly_arm_sources(read) == {'tube_front': 'match', 'tube_rear': 'match'}
    assert project.path is None and read['scheme'] == project.to_dict()
    for part in read['parts']:
        separate = tmp_path / (part['id'] + '.kim')
        write_document(separate, 'part', part)
        assert read_document(separate, 'part') == part


@pytest.mark.parametrize('choice', ['unknown', 'required', 'not_required'])
def test_damper_choice_is_explicit_not_inferred(choice):
    _, doc = make(choice)
    assert doc['damper_mount'] == choice
    assert any(n['id'] == 'damper_bracket' for n in doc['nodes']) == (choice == 'required')
    assert all(w['status'] == 'needs_design' for w in doc['welds'])


def test_project_change_yields_new_snapshot_and_original_is_untouched():
    project, doc = make('required')
    original = deepcopy(doc)
    project.front.hardpoints['lbj'].y += 30
    # The saved file still refers to its own snapshot, not the live project.
    assert weldment_source_matches(doc)
    updated = rebuild_welded_arm(doc, project)
    assert updated != doc and doc == original
    assert weldment_source_matches(updated)
    assert updated['damper_mount'] == 'required'
    assert [p['geometry']['source'] for p in updated['parts']] != [p['geometry']['source'] for p in doc['parts']]
    assert all(p['geometry']['radius_mm'] == 12 and p['geometry']['wall_mm'] == 2 for p in updated['parts'])
    project.front.type_code = 'macpherson_front'
    project.front.ensure_points()
    with pytest.raises(KimFormatError):
        rebuild_welded_arm(doc, project)
    assert doc == original


def test_saved_scheme_change_is_reported_without_silent_rebuild(tmp_path):
    _, doc = make()
    doc['scheme']['front_axle']['hardpoints']['lbj']['y'] += 25
    assert not weldment_source_matches(doc)
    assert inspect_assembly_arm_sources(doc) == {'tube_front': 'different', 'tube_rear': 'different'}
    path = tmp_path / 'stale.kima'
    write_document(path, 'assembly', doc)
    assert not weldment_source_matches(read_document(path, 'assembly'))


def test_explicit_legacy_conversion_preserves_original_and_requires_same_source(tmp_path):
    project = Project.create_default()
    old = make_lower_arm_tube_prototype('old', 'Старый черновик', project, 10, 1.5)
    path = tmp_path / 'old.kim'
    write_document(path, 'part', old)
    before = path.read_bytes()
    new = convert_legacy_tubes(read_document(path, 'part'), project, 'unknown')
    assert new['version'] == '0.2' and len(new['parts']) == 2
    assert all(p['geometry']['radius_mm'] == 10 and p['geometry']['wall_mm'] == 1.5 for p in new['parts'])
    assert path.read_bytes() == before
    project.front.hardpoints['lbj'].x += 1
    with pytest.raises(KimFormatError):
        convert_legacy_tubes(old, project, 'unknown')
    assert path.read_bytes() == before


@pytest.mark.parametrize('tamper', [
    lambda d: d.update(extra='future'),
    lambda d: d.update(damper_mount='guess'),
    lambda d: d['nodes'].append(deepcopy(d['nodes'][0])),
    lambda d: d['nodes'].pop(),
    lambda d: d['nodes'][2].update(parent='arm'),
    lambda d: d['nodes'][4].update(kind='part'),
    lambda d: d['welds'][0].update(status='welded'),
    lambda d: d['welds'].append(deepcopy(d['welds'][0])),
    lambda d: d['parts'][1]['geometry'].update(leg='front'),
    lambda d: d['parts'][0]['geometry'].update(wall_mm=12),
    lambda d: d['parts'][0]['geometry'].update(radius_mm=13),
    lambda d: d['parts'][0]['geometry']['source']['coordinates_mm'][0].__setitem__(0, 999),
])
def test_inconsistent_graph_is_rejected_without_overwriting_existing_file(tmp_path, tamper):
    _, doc = make('required')
    path = tmp_path / 'arm.kima'
    write_document(path, 'assembly', doc)
    old = path.read_bytes()
    tamper(doc)
    with pytest.raises(KimFormatError):
        validate_welded_arm(doc)
    with pytest.raises(KimFormatError):
        write_document(path, 'assembly', doc)
    assert path.read_bytes() == old and list(tmp_path.iterdir()) == [path]
