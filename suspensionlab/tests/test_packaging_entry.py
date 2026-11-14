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
    monkeypatch.setitem(sys.modules, "suspensionlab.packaging_smoke", smoke)
    monkeypatch.setattr(sys, "argv", ["app", "--packaging-check", str(report)])
    assert packaging_entry.main() == 1
    assert "expected check failure" in report.read_text(encoding="utf-8")


def test_normal_start_delegates_to_app(monkeypatch) -> None:
    app = ModuleType("suspensionlab.app")
    app.main = lambda: 17  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "suspensionlab.app", app)
    monkeypatch.setattr(sys, "argv", ["app"])
    assert packaging_entry.main() == 17
