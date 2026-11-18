"""Самодостаточный снимок схемы и параметрической заготовки: не проектирование детали."""

from copy import deepcopy

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.kim_format import (
    KimFormatError,
    compare_lower_arm_source,
    make_scheme_arm_part,
    read_document,
    rebuild_scheme_arm_part,
    write_document,
)


def test_roundtrip_contains_complete_independent_scheme_and_explicit_rebuild(tmp_path):
    project = Project.create_default()
    part = make_scheme_arm_part("front_lower_left", "Черновик рычага", project, 12, 2)
    frozen = deepcopy(part)
    path = tmp_path / "рычаг.kim"
    write_document(path, "part", part, overwrite=False)
    assert read_document(path, "part") == part
    assert part["version"] == "0.3" and part["scheme"] == project.to_dict()
    project.front.hardpoints["lbj"].y += 20
    assert part == frozen and not compare_lower_arm_source(part, project)
    updated = rebuild_scheme_arm_part(part, project)
    assert compare_lower_arm_source(updated, project) and updated["scheme"] == project.to_dict()
    assert updated["geometry"]["radius_mm"] == 12 and updated["geometry"]["wall_mm"] == 2
    assert part == frozen and read_document(path, "part") == frozen
    assert updated["id"] == part["id"] and updated["name"] == part["name"]


def test_unchanged_points_do_not_prove_entire_scheme_or_project_identity():
    project = Project.create_default()
    doc = make_scheme_arm_part("arm", "Рычаг", project, 12, 2)
    project.meta.name = "Другой проект"
    assert compare_lower_arm_source(doc, project)  # only three points and type
    assert rebuild_scheme_arm_part(doc, project)["scheme"] != doc["scheme"]


def test_changed_suspension_type_or_degenerate_points_leave_original_untouched():
    project = Project.create_default()
    doc = make_scheme_arm_part("arm", "Рычаг", project, 12, 2)
    old = deepcopy(doc)
    project.front.type_code = "macpherson_front"
    project.front.ensure_points()
    with pytest.raises(KimFormatError):
        rebuild_scheme_arm_part(doc, project)
    project = Project.create_default()
    p, q = project.front.hardpoints["lbj"], project.front.hardpoints["lca_f_in"]
    p.x, p.y, p.z = q.x, q.y, q.z
    with pytest.raises(KimFormatError):
        rebuild_scheme_arm_part(doc, project)
    assert doc == old


@pytest.mark.parametrize("tamper", [
    lambda p: p.update(algorithm="unknown"),
    lambda p: p.update(scheme=None),
    lambda p: p.update(extra="unexpected"),
    lambda p: p["scheme"].update(unexpected=True),
    lambda p: p["geometry"]["source"]["coordinates_mm"][2].__setitem__(0, 999.0),
    lambda p: p["geometry"].update(kind="prototype_lower_arm_rods"),
    lambda p: p["geometry"].update(radius_mm=10001),
    lambda p: p["geometry"].update(wall_mm=0),
])
def test_invalid_or_mismatched_part_never_overwrites_existing(tmp_path, tamper):
    part = make_scheme_arm_part("arm", "Рычаг", Project.create_default(), 12, 2)
    path = tmp_path / "part.kim"
    write_document(path, "part", part, overwrite=False)
    saved = path.read_bytes()
    tamper(part)
    with pytest.raises(KimFormatError):
        write_document(path, "part", part)
    assert path.read_bytes() == saved


def test_copy_cannot_overwrite_or_follow_destination_symlink(tmp_path):
    doc = make_scheme_arm_part("arm", "Рычаг", Project.create_default(), 12, 2)
    path = tmp_path / "part.kim"
    write_document(path, "part", doc, overwrite=False)
    before = path.read_bytes()
    with pytest.raises(KimFormatError):
        write_document(path, "part", doc, overwrite=False)
    assert path.read_bytes() == before
    link = tmp_path / "link.kim"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(KimFormatError):
        write_document(link, "part", doc, overwrite=False)
    assert path.read_bytes() == before


def test_rejects_missing_duplicate_or_unknown_version_fields(tmp_path):
    import json

    doc = make_scheme_arm_part("arm", "Рычаг", Project.create_default(), 12, 2)
    path = tmp_path / "bad.kim"
    for mutate in (lambda d: d.pop("scheme"), lambda d: d.update(version="99"),
                   lambda d: d["geometry"]["source"].update(side="right")):
        bad = deepcopy(doc)
        mutate(bad)
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(KimFormatError):
            read_document(path, "part")
    path.write_text('{"format":"kim-part","format":"kim-part"}', encoding="utf-8")
    with pytest.raises(KimFormatError):
        read_document(path, "part")


def test_legacy_rebuild_and_assembly_cannot_silently_drop_or_misversion_scheme():
    from suspensionlab.model.kim_format import make_assembly, rebuild_lower_arm_prototype

    project = Project.create_default()
    doc = make_scheme_arm_part("arm", "Рычаг", project, 12, 2)
    old = deepcopy(doc)
    with pytest.raises(KimFormatError):
        rebuild_lower_arm_prototype(doc, project)
    with pytest.raises(KimFormatError):
        make_assembly("Сборка", [doc], [{"id": "one", "part_id": "arm", "translation_mm": [0, 0, 0]}], project)
    assert doc == old
