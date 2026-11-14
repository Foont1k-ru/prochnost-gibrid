"""Восстановление снимка и история команд без Qt."""
import copy

import pytest

from suspensionlab.model.commands import UndoStack, ValueCommand
from suspensionlab.model.entities import Project
from suspensionlab.model.snapshot_restore import RestoreSnapshotCommand, prepare_snapshot
from suspensionlab.model.templates import list_templates, load_template


@pytest.mark.parametrize("info", list_templates(), ids=lambda info: info.key)
def test_current_template_snapshots_prepare_without_change(info):
    project = load_template(info.key)
    data = project._to_dict_without_b()
    before = copy.deepcopy(data)
    restored = prepare_snapshot(data)
    assert data == before
    for field in ("meta", "vehicle", "front_axle", "rear_axle"):
        assert restored.to_dict()[field] == data[field]


def test_restore_undo_redo_retains_objects_and_prior_and_later_edit_history():
    project = load_template("ring")
    original = project.vehicle
    snapshot = project._to_dict_without_b()
    project.path = "original.susp.json"
    project.add_snapshot("один")
    project.locks["example"] = True
    project.model_b = project.clone_as_model_b()
    snapshots, locks, view, model_b = project.snapshots, project.locks, project.view, project.model_b
    stack = UndoStack()
    initial = original.mass_kg
    stack.push(ValueCommand(original, "mass_kg", initial, initial + 10))
    command = RestoreSnapshotCommand(project, prepare_snapshot(snapshot))
    stack.push(command)
    restored_vehicle = project.vehicle
    assert restored_vehicle is not original and restored_vehicle.mass_kg == initial
    assert project.snapshots is snapshots and project.locks is locks and project.view is view
    assert project.model_b is model_b and project.path == "original.susp.json"
    stack.push(ValueCommand(restored_vehicle, "mass_kg", initial, initial + 20))
    stack.undo()
    stack.undo()
    assert project.vehicle is original and project.vehicle.mass_kg == initial + 10
    stack.undo()
    assert project.vehicle is original and project.vehicle.mass_kg == initial
    stack.redo()
    stack.redo()
    assert project.vehicle is restored_vehicle and project.vehicle.mass_kg == initial
    stack.redo()
    assert project.vehicle.mass_kg == initial + 20


@pytest.mark.parametrize("corrupt", ["empty", "schema", "missing", "unknown_type", "point", "nan"])
def test_invalid_snapshots_rejected_without_mutating_input(corrupt):
    data = load_template("ring")._to_dict_without_b()
    if corrupt == "empty":
        data = {}
    elif corrupt == "schema":
        data["schema_version"] = "99.0"
    elif corrupt == "missing":
        del data["vehicle"]["mass_kg"]
    elif corrupt == "unknown_type":
        data["front_axle"]["type"] = "unknown"
    elif corrupt == "point":
        del data["front_axle"]["hardpoints"]["ubj"]
    elif corrupt == "nan":
        data["vehicle"]["mass_kg"] = float("inf")
    before = copy.deepcopy(data)
    with pytest.raises(ValueError):
        prepare_snapshot(data)
    assert data == before


def test_snapshot_input_is_isolated_from_restored_objects():
    project = Project.create_default()
    data = project._to_dict_without_b()
    restored = prepare_snapshot(data)
    restored.vehicle.mass_kg += 50
    assert data["vehicle"]["mass_kg"] != restored.vehicle.mass_kg
