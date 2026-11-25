"""Проверка событий в реальных контроллере, анализе, STEP-просмотре и запуске."""
from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QSettings

from suspensionlab import diagnostic_events
from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.model.project_io import ProjectIOError
from suspensionlab.ui.analysis_dialog import AnalysisDialog
from suspensionlab.ui.cad_preview_dialog import CadPreviewDialog
from suspensionlab.ui.controller import AppController
from suspensionlab.ui.main_window import MainWindow
from suspensionlab.ui.point_table_dialog import PointTableDialog


@pytest.fixture
def events(monkeypatch):
    stream = io.StringIO()
    logger = logging.Logger("isolated.events", logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    monkeypatch.setattr(diagnostic_events, "_LOG", logger)
    yield stream
    handler.close()


def records(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_allowlist_excludes_untrusted_text_and_unknown_fields(events):
    diagnostic_events.event("cad.start", operation=1, deviation_um=2000)
    diagnostic_events.event("cad.start", operation=1, filename="secret.step")
    diagnostic_events.event("project.open", result="C:/private/test.susp.json")
    diagnostic_events.event("project.open", result="bad\ntext")
    diagnostic_events.event("not.registered", result="ok")
    diagnostic_events.event("cad.start", operation=1, deviation_um=2.0)
    assert len(records(events)) == 1
    assert "secret" not in events.getvalue() and "private" not in events.getvalue()


def test_project_operations_and_failed_autosave_log_without_paths(events, tmp_path, monkeypatch):
    c = AppController()
    c.project.meta.name = "private-project-data"
    path = tmp_path / "secret-project.susp.json"
    c.save_project(path)
    c.open_project(path)
    with pytest.raises(ProjectIOError):
        c.open_project(tmp_path / "missing-secret.susp.json")
    monkeypatch.setattr("suspensionlab.ui.controller.autosave_path", lambda: (_ for _ in ()).throw(OSError("secret")))
    assert not c.autosave()
    logs = records(events)
    assert [r["result"] for r in logs if r["event"] == "project.save"] == ["start", "ok"]
    assert [r["result"] for r in logs if r["event"] == "project.open"] == ["start", "ok", "start", "failed"]
    assert any(r["event"] == "project.autosave" and r["result"] == "failed" for r in logs)
    assert "secret" not in events.getvalue() and "private-project-data" not in events.getvalue()


def test_sweep_and_point_edit_report_counts_not_coordinates(events, qtbot):
    controller = AppController()
    controller.new_project("ring")
    dialog = AnalysisDialog(controller)
    qtbot.addWidget(dialog)
    dialog._from.setValue(-2)
    dialog._to.setValue(2)
    dialog._spring.setChecked(True)
    dialog._spring_length.setValue(320)
    dialog._damper.setChecked(True)
    dialog._damper_min.setValue(205)
    dialog._damper_max.setValue(325)
    dialog._calculate()
    report = next(r for r in records(events) if r["event"] == "analysis.result")
    assert report["rows"] == 5 and report["damper_conflicts"] > 0
    assert report["missing"] == 0 and report["result"] == "ok"
    point_table = PointTableDialog(controller)
    qtbot.addWidget(point_table)
    point_table._table.item(0, 4).setText("bad private text")
    point_table._apply_changes()
    assert records(events)[-1]["result"] == "invalid"
    point_table._table.item(0, 4).setText("123456.7")
    point_table._apply_changes()
    last = records(events)[-1]
    assert last["event"] == "points.apply" and last["result"] == "ok" and last["points"] == 1
    assert "123456.7" not in events.getvalue() and "private" not in events.getvalue()


def test_cad_outcomes_are_correlated_without_file_or_model_names(events, qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("suspensionlab.ui.cad_preview_dialog._CadReader.start", lambda self: None)
    dialog = CadPreviewDialog()
    qtbot.addWidget(dialog)
    dialog.load_file(tmp_path / "secret-model.step")
    assert str(dialog._operation) in dialog._event_label.text()
    mesh = CadMesh(np.zeros((2, 3, 3)), 3, skipped_faces=1)
    dialog._show_mesh(mesh)
    dialog._finished()
    dialog.load_file(tmp_path / "other-secret.step")
    dialog._show_error("timeout")
    dialog._finished()
    dialog.load_file(tmp_path / "last-secret.step")
    dialog._show_error("cancelled")
    dialog._finished()
    logs = records(events)
    starts = [r for r in logs if r["event"] == "cad.start"]
    ends = [r for r in logs if r["event"] == "cad.result"]
    assert [r["operation"] for r in starts] == [r["operation"] for r in ends]
    assert [r["result"] for r in ends] == ["ok", "timeout", "cancelled"]
    assert ends[0]["skipped"] == 1 and ends[0]["triangles"] == 2
    assert all(r["duration_ms"] >= 0 for r in ends)
    assert "secret" not in events.getvalue()


def test_event_log_menu_opens_correct_file(qtbot, tmp_path, monkeypatch):
    window = MainWindow(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    path = tmp_path / "events.log"
    seen = []
    monkeypatch.setattr("suspensionlab.ui.main_window.diagnostic_log_path", lambda: path)
    monkeypatch.setattr(window, "_show_text_file", lambda p, title: seen.append((p, title)))
    window.action_events.trigger()
    assert seen and seen[0][0] == path


def test_setup_failure_and_rotation_without_touching_technical_log(tmp_path, monkeypatch):
    logger = logging.Logger("isolated.file.events")
    monkeypatch.setattr(diagnostic_events, "_LOG", logger)
    monkeypatch.setattr(diagnostic_events, "_configured", False)
    assert not diagnostic_events.setup_event_logging(tmp_path / "missing" / "events.log")
    assert diagnostic_events.setup_event_logging(tmp_path / "events.log")
    try:
        for _ in range(14000):
            diagnostic_events.event("cad.start", operation=1, deviation_um=2000)
        for handler in logger.handlers:
            handler.flush()
        assert (tmp_path / "events.log.1").is_file()
        assert not (tmp_path / "suspensionlab.log").exists()
    finally:
        for handler in logger.handlers:
            handler.close()


def test_actual_startup_and_clean_event_loop_exit_are_logged(tmp_path):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", APPDATA=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path))
    entry = Path(__file__).resolve().parents[1] / "packaging_entry.py"
    report = tmp_path / "report.txt"
    process = subprocess.run([sys.executable, str(entry), "--packaging-startup-check", str(report)],
                             env=env, capture_output=True, text=True, timeout=60, check=False)
    assert process.returncode == 0, process.stdout + process.stderr
    assert report.read_text(encoding="utf-8").strip() == "OK"
    path = tmp_path / "SuspensionLab" / "logs" / "events.log"
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line[line.index("{"):]) for line in lines]
    assert [r["event"] for r in parsed] == ["session.start", "session.end"]
    assert parsed[0]["session"] == parsed[1]["session"] and parsed[1]["exit_code"] == 0
    assert parsed[0]["pyside"] and parsed[0]["python"] and parsed[0]["os"]


def test_inventory_logs_outcome_and_counts_without_model_content(events, qtbot, tmp_path):
    from suspensionlab.ui.step_inventory_dialog import StepInventoryDialog

    path = tmp_path / "private-assembly.step"
    path.write_text("ISO-10303-21;HEADER;FILE_SCHEMA(('AP242'));ENDSEC;DATA;"
                    "#1=PRODUCT('secret-id','secret-part','',());ENDSEC;END-ISO-10303-21;", encoding="ascii")
    dialog = StepInventoryDialog()
    qtbot.addWidget(dialog)
    dialog.load_file(path)
    assert str(dialog._operation) in dialog._event_label.text()
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    dialog.load_file(tmp_path / "missing-secret.step")
    qtbot.waitUntil(lambda: dialog._reader is None, timeout=10000)
    logs = records(events)
    starts = [r for r in logs if r["event"] == "inventory.start"]
    ends = [r for r in logs if r["event"] == "inventory.result"]
    assert [r["operation"] for r in starts] == [r["operation"] for r in ends]
    assert ends[0]["result"] == "ok" and ends[0]["products"] == 1
    assert ends[1]["result"] == "failed"
    assert "secret" not in events.getvalue()


def test_antiroll_and_equilibrium_log_success_and_failure(events, qtbot):
    from suspensionlab.core.equilibrium import SpringEquilibrium
    from suspensionlab.ui.antiroll_dialog import AntiRollDialog
    from suspensionlab.ui.equilibrium_dialog import EquilibriumDialog

    c = AppController()
    c.new_project("ring")
    antiroll = AntiRollDialog(c)
    qtbot.addWidget(antiroll)
    antiroll._calculate()
    assert records(events)[-1]["result"] == "failed"
    antiroll._from.setValue(0)
    antiroll._to.setValue(1)
    antiroll._axis_x.setText("-250")
    antiroll._axis_z.setText("320")
    antiroll._rate.setText("1000")
    antiroll._calculate()
    anti_result = records(events)[-1]
    assert anti_result["event"] == "antiroll.result" and anti_result["result"] == "ok"
    assert anti_result["rows"] == 2
    eq = EquilibriumDialog(c)
    qtbot.addWidget(eq)
    eq._calculate()
    assert records(events)[-1]["result"] == "failed"
    load = SpringEquilibrium(c.project.front, 230, coil_bind_length_mm=150).evaluate(12, 1).wheel_support_n
    eq._length.setValue(230)
    eq._bind.setValue(150)
    eq._load.setValue(load)
    eq._calculate()
    balance = records(events)[-1]
    assert balance["event"] == "equilibrium.result" and balance["result"] == "ok"
    assert balance["samples"] > 0
    assert "-250" not in events.getvalue()


def test_automatic_windows_packaging_is_paused():
    root = Path(__file__).resolve().parents[2]
    ci = (root / ".github/workflows/suspensionlab.yml").read_text(encoding="utf-8")
    build = (root / ".github/workflows/windows.yml").read_text(encoding="utf-8")
    assert "on: [workflow_dispatch]" in build
    assert "github.event_name == 'workflow_dispatch' && inputs.build_experimental == true" in ci
    assert "default: false" in ci


def test_point_import_events_report_outcome_without_path_or_coordinate(events, qtbot, tmp_path):
    import csv

    from PySide6.QtCore import QTimer

    from suspensionlab.ui.point_import_dialog import PointImportDialog

    c = AppController()
    dialog = PointTableDialog(c)
    qtbot.addWidget(dialog)
    path = tmp_path / 'secret-coordinates.csv'
    dialog.export_csv(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.reader(stream))
    rows[1][5] = '123456.7'
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        csv.writer(stream).writerows(rows)
    QTimer.singleShot(0, lambda: dialog.findChild(PointImportDialog)._apply.click())
    dialog.import_csv(path)
    imports = [r for r in records(events) if r['event'] == 'points.import']
    assert [r['result'] for r in imports] == ['preview', 'ok']
    assert imports[-1]['points'] == 1 and imports[-1]['cells'] == 1
    assert 'secret' not in events.getvalue() and '123456.7' not in events.getvalue()


def test_cad_performance_is_opt_in_bounded_and_excludes_model_data(events, qtbot, monkeypatch, tmp_path):
    from suspensionlab.ui.canvas import cad_preview

    time = [100.0]
    monkeypatch.setattr(cad_preview, 'perf_counter', lambda: time[0])
    original = cad_preview.interaction_geometry
    def slow_interaction(mesh, highlight):
        time[0] += .2
        return original(mesh, highlight)
    monkeypatch.setattr(cad_preview, 'interaction_geometry', slow_interaction)
    dialog = CadPreviewDialog(settings=QSettings(str(tmp_path / 'secret.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(dialog)
    view = dialog._view
    model = CadMesh(np.array([[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]]), 1,
                    part_names=('private-part',), triangle_parts=np.array([0]))
    assert not dialog._performance_diagnostics.isChecked()
    view.set_mesh(model)
    assert not records(events)
    dialog.show()
    dialog._performance_diagnostics.setChecked(True)
    assert view._perf_timer.isActive()
    view.set_mesh(model, np.array([True]))
    time[0] += 1.0
    view._perf_tick()
    log = records(events)
    assert [r['stage'] for r in log] == ['enabled', 'mesh_interaction', 'mesh_setup', 'event_loop']
    assert log[1]['duration_ms'] == 200 and log[1]['renderer'] == 'cpu' and log[1]['triangles'] == 1
    assert log[-1]['duration_ms'] >= 750
    assert all(set(record) == {'session', 'event', 'stage', 'renderer', 'duration_ms', 'triangles'} for record in log)
    assert 'private-part' not in events.getvalue() and 'secret.ini' not in events.getvalue()
    for _ in range(250):
        view._perf_record('event_loop', 500)
    assert len(records(events)) == 200
    dialog._performance_diagnostics.setChecked(False)
    assert not view._perf_timer.isActive()
    view.set_mesh(model)
    assert len(records(events)) == 200
    dialog.close()


def test_cad_performance_timer_stops_when_hidden(events, qtbot, tmp_path):
    dialog = CadPreviewDialog(settings=QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._performance_diagnostics.setChecked(True)
    assert dialog._view._perf_timer.isActive()
    dialog.hide()
    assert not dialog._view._perf_timer.isActive()
    dialog.show()
    assert dialog._view._perf_timer.isActive()
    dialog._performance_diagnostics.setChecked(False)
    assert [r['stage'] for r in records(events)] == ['enabled', 'disabled']
    dialog.close()


def test_cad_performance_records_cpu_render_and_pick(events, qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import QPoint, Qt

    from suspensionlab.ui.canvas import cad_preview

    time = [0.0]
    monkeypatch.setattr(cad_preview, 'perf_counter', lambda: time[0])
    rasterize, pick = cad_preview.rasterize, cad_preview.pick_triangle
    def slow_rasterize(*args, **kwargs):
        time[0] += .13
        return rasterize(*args, **kwargs)
    def slow_pick(*args, **kwargs):
        time[0] += .17
        return pick(*args, **kwargs)
    monkeypatch.setattr(cad_preview, 'rasterize', slow_rasterize)
    monkeypatch.setattr(cad_preview, 'pick_triangle', slow_pick)
    dialog = CadPreviewDialog(settings=QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(dialog)
    view = dialog._view
    model = CadMesh(np.array([[[-1., 0., -1.], [1., 0., -1.], [0., 0., 1.]]]), 1,
                    part_names=('part',), triangle_parts=np.array([0]))
    view.set_mesh(model)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog._performance_diagnostics.setChecked(True)
    view._frame_key = None
    view.update()
    qtbot.waitUntil(lambda: any(r.get('stage') == 'frame_cpu' for r in records(events)))
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(view.width() // 2, view.height() // 2))
    log = records(events)
    assert any(r.get('stage') == 'frame_cpu' and r['duration_ms'] == 130 for r in log)
    assert any(r.get('stage') == 'pick' and r['duration_ms'] == 170 and r['renderer'] == 'cpu' for r in log)
    dialog.close()


def test_cad_performance_records_gl_setup_render_and_pick_with_mock(events, qtbot, monkeypatch, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QColor, QImage

    from suspensionlab.ui.canvas import cad_gl_renderer, cad_preview

    clock = [10.0]
    monkeypatch.setattr(cad_preview, 'perf_counter', lambda: clock[0])
    class FakeRenderer:
        vendor, renderer, version = 'test', 'test', 'test'
        def __init__(self):
            clock[0] += .1
        def set_mesh(self, *args):
            clock[0] += .2
        def render(self, center, yaw, elevation, zoom, width, height, margin, offset, highlight, through, bg):
            clock[0] += .12
            image = QImage(width, height, QImage.Format.Format_RGBA8888)
            image.fill(QColor('black'))
            return image
        def pick(self, *args):
            clock[0] += .15
            return 0
        def close(self):
            pass
    monkeypatch.setattr(cad_gl_renderer, 'CadGlRenderer', FakeRenderer)
    dialog = CadPreviewDialog(settings=QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(dialog)
    model = CadMesh(np.array([[[-1., 0., -1.], [1., 0., -1.], [0., 0., 1.]]]), 1,
                    part_names=('part',), triangle_parts=np.array([0]))
    view = dialog._view
    view.set_mesh(model)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog._performance_diagnostics.setChecked(True)
    view._renderer_button.click()
    qtbot.waitUntil(lambda: any(r.get('stage') == 'frame_gl' for r in records(events)))
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(view.width() // 2, view.height() // 2))
    log = records(events)
    for stage, duration in (('gpu_setup', 300), ('frame_gl', 120), ('pick', 150)):
        assert any(r.get('stage') == stage and r['duration_ms'] == duration and r['renderer'] == 'gl' for r in log)
    dialog.close()


def test_cad_performance_times_ui_pick_even_on_error(events, qtbot, monkeypatch, tmp_path):
    from suspensionlab.ui import cad_preview_dialog
    from suspensionlab.ui.canvas import cad_preview

    clock = [20.0]
    monkeypatch.setattr(cad_preview, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(cad_preview_dialog, 'perf_counter', lambda: clock[0])
    dialog = CadPreviewDialog(settings=QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(dialog)
    dialog._performance_diagnostics.setChecked(True)
    def failed_pick(index):
        clock[0] += .09
        raise ValueError('private-geometry-name')
    monkeypatch.setattr(dialog, '_apply_triangle_pick', failed_pick)
    with pytest.raises(ValueError):
        dialog._pick_triangle(0)
    assert records(events)[-1]['stage'] == 'pick_ui'
    assert records(events)[-1]['duration_ms'] == 90
    assert 'private-geometry-name' not in events.getvalue()
    dialog.close()
