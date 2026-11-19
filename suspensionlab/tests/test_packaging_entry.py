"""Маршрутизация входа пробной сборки без запуска Qt."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import packaging_entry


def test_packaging_check_writes_success(tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "result.txt"
    smoke = ModuleType("suspensionlab.packaging_smoke")
    calls: list[str] = []
    smoke.run_packaging_check = lambda: calls.append("checked")  # type: ignore[attr-defined]
    smoke.run_startup_check = lambda: calls.append("startup")  # type: ignore[attr-defined]
    smoke.run_cad_check = lambda: calls.append("cad")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suspensionlab.packaging_smoke", smoke)
    monkeypatch.setattr(sys, "argv", ["app", "--packaging-check", str(report)])
    assert packaging_entry.main() == 0
    assert calls == ["checked"]
    assert report.read_text(encoding="utf-8") == "OK\n"


def test_packaging_check_reports_failure(tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "result.txt"
    smoke = ModuleType("suspensionlab.packaging_smoke")
    def fail() -> None:
        raise ValueError("expected check failure")
    smoke.run_packaging_check = fail  # type: ignore[attr-defined]
    smoke.run_startup_check = fail  # type: ignore[attr-defined]
    smoke.run_cad_check = fail  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suspensionlab.packaging_smoke", smoke)
    monkeypatch.setattr(sys, "argv", ["app", "--packaging-check", str(report)])
    assert packaging_entry.main() == 1
    assert "expected check failure" in report.read_text(encoding="utf-8")


def test_packaging_startup_check_has_separate_route(tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "startup.txt"
    smoke = ModuleType("suspensionlab.packaging_smoke")
    calls: list[str] = []
    smoke.run_packaging_check = lambda: calls.append("checked")  # type: ignore[attr-defined]
    smoke.run_startup_check = lambda: calls.append("startup")  # type: ignore[attr-defined]
    smoke.run_cad_check = lambda: calls.append("cad")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suspensionlab.packaging_smoke", smoke)
    monkeypatch.setattr(sys, "argv", ["app", "--packaging-startup-check", str(report)])
    assert packaging_entry.main() == 0 and calls == ["startup"]
    assert report.read_text(encoding="utf-8") == "OK\n"



def test_packaging_cad_check_has_separate_route(tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "cad.txt"
    smoke = ModuleType("suspensionlab.packaging_smoke")
    calls: list[str] = []
    smoke.run_packaging_check = lambda: calls.append("checked")  # type: ignore[attr-defined]
    smoke.run_startup_check = lambda: calls.append("startup")  # type: ignore[attr-defined]
    smoke.run_cad_check = lambda: calls.append("cad")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suspensionlab.packaging_smoke", smoke)
    monkeypatch.setattr(sys, "argv", ["app", "--packaging-cad-check", str(report)])
    assert packaging_entry.main() == 0 and calls == ["cad"]
    assert report.read_text(encoding="utf-8") == "OK\n"

def test_cad_worker_is_dispatched_before_gui(monkeypatch) -> None:
    worker = ModuleType("suspensionlab.core.cad_worker")
    called: list[list[str]] = []
    worker.main = lambda args: called.append(args) or 9  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suspensionlab.core.cad_worker", worker)
    monkeypatch.setattr(sys, "argv", ["app", "--cad-preview-worker", "source", "output", "report", "2.0"])
    assert packaging_entry.main() == 9 and called == [["source", "output", "report", "2.0"]]


def test_normal_start_delegates_to_app(monkeypatch) -> None:
    app = ModuleType("suspensionlab.app")
    app.main = lambda: 17  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suspensionlab.app", app)
    monkeypatch.setattr(sys, "argv", ["app"])
    assert packaging_entry.main() == 17


def test_weldment_worker_is_dispatched_before_gui(monkeypatch) -> None:
    worker = ModuleType("suspensionlab.core.cad_weldment_worker")
    called: list[list[str]] = []
    worker.main = lambda args: called.append(args) or 11  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suspensionlab.core.cad_weldment_worker", worker)
    monkeypatch.setattr(sys, "argv", ["app", "--weldment-preview-worker", "source", "output", "report", "2.0"])
    assert packaging_entry.main() == 11 and called == [["source", "output", "report", "2.0"]]


def test_sketch_worker_routes_both_old_and_direction_arguments(monkeypatch) -> None:
    worker = ModuleType("suspensionlab.core.sketch_solid_worker")
    called: list[list[str]] = []
    worker.main = lambda args: called.append(args) or 13  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suspensionlab.core.sketch_solid_worker", worker)
    for args in (["source", "output", "report", "2.0"],
                 ["source", "output", "report", "2.0", "symmetric"],
                 ["source", "output", "report", "2.0", "negative", "1.0"],
                 ["source", "output", "report", "2.0", "negative", "1.0", "positive"],
                 ["source", "output", "report", "2.0", "negative", "1.0", "positive", "holes.json"]):
        monkeypatch.setattr(sys, "argv", ["app", "--sketch-solid-worker", *args])
        assert packaging_entry.main() == 13 and called[-1] == args


def test_tube_notch_worker_is_dispatched_before_gui(monkeypatch) -> None:
    worker = ModuleType('suspensionlab.core.cad_tube_notch_worker')
    called: list[list[str]] = []
    worker.main = lambda args: called.append(args) or 23  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'suspensionlab.core.cad_tube_notch_worker', worker)
    args = ['source', 'output', 'report', 'tube_front', 'housing_front', '1.5']
    monkeypatch.setattr(sys, 'argv', ['app', '--tube-notch-worker', *args])
    assert packaging_entry.main() == 23 and called == [args]


def test_assembly_projection_worker_is_dispatched_before_gui(monkeypatch) -> None:
    worker = ModuleType('suspensionlab.core.cad_assembly_projection_worker')
    called: list[list[str]] = []
    worker.main = lambda args: called.append(args) or 19  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'suspensionlab.core.cad_assembly_projection_worker', worker)
    monkeypatch.setattr(sys, 'argv', ['app', '--assembly-projection-worker', 'source', 'output', 'report'])
    assert packaging_entry.main() == 19 and called == [['source', 'output', 'report']]


def test_sequence_worker_routes_one_to_four_cutters_before_gui(monkeypatch) -> None:
    worker = ModuleType('suspensionlab.core.cad_tube_notch_sequence_worker')
    called: list[list[str]] = []
    worker.main = lambda args: called.append(args) or 29  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'suspensionlab.core.cad_tube_notch_sequence_worker', worker)
    cutters = ['housing_front', 'housing_rear', 'ball_plate', 'tube_rear']
    for count in range(1, 5):
        args = ['source', 'output', 'report', 'tube_front', *cutters[:count]]
        monkeypatch.setattr(sys, 'argv', ['app', '--tube-notch-sequence-worker', *args])
        assert packaging_entry.main() == 29 and called[-1] == args
