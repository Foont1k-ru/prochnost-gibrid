"""Сохранение, загрузка, миграция и валидация файлов проектов."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from suspensionlab.model.entities import Project
from suspensionlab.model.project_io import (
    ProjectIOError,
    load_project,
    migrate,
    project_to_json,
    save_project,
)
from suspensionlab.model.templates import list_templates, load_template


def test_save_and_load_roundtrip(tmp_path: Path, project) -> None:
    project.front.setup.camber_deg = -3.25
    project.front.hardpoints["ubj"].z = 412.5
    project.meta.name = "Тестовый проект"
    path = save_project(project, tmp_path / "probe")
    assert path.name.endswith(".susp.json")

    loaded = load_project(path)
    assert loaded.meta.name == "Тестовый проект"
    assert loaded.front.setup.camber_deg == pytest.approx(-3.25)
    assert loaded.front.hardpoints["ubj"].z == pytest.approx(412.5)
    assert loaded.rear.type_code == project.rear.type_code


def test_save_adds_extension(tmp_path: Path, project) -> None:
    path = save_project(project, tmp_path / "file.json")
    assert path.name == "file.susp.json"


def test_broken_json_reports_key(tmp_path: Path) -> None:
    path = tmp_path / "broken.susp.json"
    path.write_text("{ это не json", encoding="utf-8")
    with pytest.raises(ProjectIOError) as error:
        load_project(path)
    assert error.value.message_key == "error.project.broken_json"
    assert "line" in error.value.params


def test_wrong_structure_reports_key(tmp_path: Path) -> None:
    path = tmp_path / "list.susp.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ProjectIOError) as error:
        load_project(path)
    assert error.value.message_key == "error.project.bad_structure"


def test_missing_file_reports_key(tmp_path: Path) -> None:
    with pytest.raises(ProjectIOError) as error:
        load_project(tmp_path / "nope.susp.json")
    assert error.value.message_key == "error.project.read_failed"


def test_migration_from_0_9() -> None:
    legacy = {
        "schema_version": "0.9",
        "meta": {"name": "Старый проект"},
        "vehicle": {"mass_kg": 1000},
        "front": {
            "type": "double_wishbone",
            "hardpoints": {"ubj": [-5.0, 655.0, 430.0], "lbj": [0.0, 690.0, 145.0]},
            "lengths": {"upper": 340.0},
        },
        "rear": {"type": "multilink_rear", "hardpoints": {"toe_in": [-260, 300, 300]}},
    }
    migrated = migrate(legacy)
    assert migrated["schema_version"] == "1.0"
    assert "front_axle" in migrated and "front" not in migrated
    assert migrated["front_axle"]["hardpoints"]["ubj"] == {"x": -5.0, "y": 655.0, "z": 430.0}
    project = Project.from_dict(migrated)
    assert project.meta.name == "Старый проект"
    assert project.front.hardpoints["ubj"].z == pytest.approx(430.0)


def test_project_from_json_text(project) -> None:
    text = project_to_json(project)
    data = json.loads(text)
    restored = Project.from_dict(data)
    assert restored.vehicle.mass_kg == pytest.approx(project.vehicle.mass_kg)


def test_all_templates_load_and_validate() -> None:
    from suspensionlab.model.validation import validate_project

    templates = list_templates()
    assert len(templates) >= 3
    for info in templates:
        project = load_template(info.key)
        issues = validate_project(project)
        errors = [issue for issue in issues if issue.severity == "error"]
        assert not errors, f"{info.key}: {[issue.key for issue in errors]}"


def test_locks_survive_roundtrip(project) -> None:
    project.locks["setup.camber"] = True
    restored = Project.from_dict(project.to_dict())
    assert restored.locks.get("setup.camber") is True


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_failed_atomic_save_preserves_existing_file_and_project_path(tmp_path, project, monkeypatch, operation):
    from suspensionlab.model import project_io

    target = tmp_path / "existing.susp.json"
    target.write_bytes(b"previous contents")
    project.path = "previous-project.susp.json"

    def fail(*args):
        raise OSError("simulated failure")

    monkeypatch.setattr(project_io.os, operation, fail)
    with pytest.raises(ProjectIOError) as error:
        save_project(project, target)
    assert error.value.message_key == "error.project.write_failed"
    assert target.read_bytes() == b"previous contents"
    assert project.path == "previous-project.susp.json"
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_serialization_failure_does_not_touch_existing_file(tmp_path, project, monkeypatch):
    from suspensionlab.model import project_io

    target = tmp_path / "existing.susp.json"
    target.write_text("old", encoding="utf8")
    project.path = "old-path"

    def fail(_project):
        raise TypeError("not serializable")

    monkeypatch.setattr(project_io, "project_to_json", fail)
    with pytest.raises(ProjectIOError) as error:
        save_project(project, target)
    assert error.value.message_key == "error.project.write_failed"
    assert target.read_text(encoding="utf8") == "old"
    assert project.path == "old-path"
    assert [p.name for p in tmp_path.iterdir()] == [target.name]


def test_atomic_save_follows_existing_symlink_and_preserves_mode(tmp_path, project):
    import os
    import stat

    if os.name == "nt":
        pytest.skip("Символические ссылки на Windows могут требовать специальных прав")
    real = tmp_path / "real.susp.json"
    real.write_text("old", encoding="utf8")
    real.chmod(0o640)
    link = tmp_path / "link.susp.json"
    link.symlink_to(real.name)
    assert save_project(project, link) == link
    assert link.is_symlink()
    assert stat.S_IMODE(real.stat().st_mode) == 0o640
    assert load_project(link).to_dict() == project.to_dict()


def test_partial_write_failure_does_not_replace_previous_file(tmp_path, project, monkeypatch):
    from suspensionlab.model import project_io

    target = tmp_path / "existing.susp.json"
    target.write_bytes(b"previous contents")
    real_factory = project_io.tempfile.NamedTemporaryFile

    class PartialWriter:
        def __init__(self, handle):
            self.handle = handle
            self.name = handle.name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, text):
            self.handle.write(text[:20])
            raise OSError("partial write")

    monkeypatch.setattr(project_io.tempfile, "NamedTemporaryFile", lambda **kwargs: PartialWriter(real_factory(**kwargs)))
    with pytest.raises(ProjectIOError):
        save_project(project, target)
    assert target.read_bytes() == b"previous contents"
    assert [p.name for p in tmp_path.iterdir()] == [target.name]
