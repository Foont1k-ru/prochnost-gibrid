"""Протокол и изолированный предварительный просмотр подрезки."""
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from suspensionlab.core.cad_transport import CadPreviewError
from suspensionlab.core.cad_tube_notch_job import TubeNotchPreviewJob, parse_notch_preview
from suspensionlab.model.entities import Project
from suspensionlab.model.scheme_arm_assembly import make_scheme_arm_assembly


def document():
    project = Project.create_default()
    for code, xyz in {'lca_f_in': (0, 0, 0), 'lca_r_in': (100, 0, 0), 'lbj': (0, 100, 0)}.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    return make_scheme_arm_assembly(project, 10, 2, {'axis': 'x', 'outer_radius_mm': 14,
                                                       'bore_radius_mm': 7, 'length_mm': 24})


def projection():
    return {'views': {key: [[0, 0, 1, 1]] for key in ('XY', 'XZ', 'YZ')},
            'bounds_mm': [0, 0, 0, 1, 1, 1]}


def test_parser_rejects_unsafe_or_inconsistent_data():
    valid = {'before': projection(), 'after': projection()}
    result = parse_notch_preview(valid)
    assert result.before.bounds_mm == result.after.bounds_mm
    bad_bounds = projection()
    bad_bounds['bounds_mm'] = [0, 0, 0, 2, 1, 1]
    bad_lines = projection()
    bad_lines['views']['XY'] = [[0, 0, 1, float('nan')]]
    for data in ({}, {'before': projection()}, {**valid, 'extra': 1},
                 {**valid, 'after': bad_bounds}, {**valid, 'after': bad_lines}):
        with pytest.raises(CadPreviewError, match='output'):
            parse_notch_preview(data)


def test_cancel_and_invalid_pair_do_not_start():
    job = TubeNotchPreviewJob()
    job.cancel()
    with pytest.raises(CadPreviewError, match='cancelled'):
        job.run(document(), 'tube_front', 'housing_front')
    with pytest.raises(CadPreviewError, match='unsupported_pair'):
        TubeNotchPreviewJob().run(document(), 'not_a_tube', 'housing_front')


def test_timeout_kills_and_reaps_worker(monkeypatch):
    from suspensionlab.core import cad_tube_notch_job

    class Process:
        killed = False
        waits = 0
        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired('notch', timeout)
            return -1
        def kill(self):
            self.killed = True
        def poll(self):
            return None
    process = Process()
    monkeypatch.setattr(cad_tube_notch_job.subprocess, 'Popen', lambda *args, **kwargs: process)
    with pytest.raises(CadPreviewError, match='timeout'):
        TubeNotchPreviewJob().run(document(), 'tube_front', 'housing_front', timeout=0.01)
    assert process.killed and process.waits == 2


def test_malformed_worker_output_rejected(monkeypatch):
    from suspensionlab.core import cad_tube_notch_job

    class Process:
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0
    def start(command, **_kwargs):
        output, report = Path(command[-4]), Path(command[-3])
        report.write_text('{"status":"ok"}', encoding='utf-8')
        output.write_text('{}', encoding='utf-8')
        return Process()
    monkeypatch.setattr(cad_tube_notch_job.subprocess, 'Popen', start)
    with pytest.raises(CadPreviewError, match='output'):
        TubeNotchPreviewJob().run(document(), 'tube_front', 'housing_front')


@pytest.mark.parametrize(('axis', 'tube', 'housing'), [
    ('x', 'tube_front', 'housing_front'), ('y', 'tube_front', 'housing_front'),
    ('z', 'tube_front', 'housing_front'), ('x', 'tube_rear', 'housing_rear'),
])
def test_isolated_cad_worker_before_after(axis, tube, housing):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.model.scheme_arm_assembly import set_assembly_axis

    doc = set_assembly_axis(document(), axis)
    saved = deepcopy(doc)
    result = TubeNotchPreviewJob().run(doc, tube, housing, timeout=60)
    assert result.before.bounds_mm == result.after.bounds_mm
    assert all(len(lines) > 0 for lines in result.before.views + result.after.views)
    assert any(a != b for a, b in zip(result.before.views, result.after.views, strict=True))
    assert doc == saved


def test_isolated_cad_worker_no_overlap():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    doc = document()
    saved = deepcopy(doc)
    with pytest.raises(CadPreviewError, match='no_overlap'):
        TubeNotchPreviewJob().run(doc, 'tube_front', 'housing_rear', timeout=60)
    assert doc == saved


def test_worker_crash_without_report(monkeypatch):
    from suspensionlab.core import cad_tube_notch_job

    class Process:
        def wait(self, timeout=None):
            return 1
    monkeypatch.setattr(cad_tube_notch_job.subprocess, 'Popen', lambda *args, **kwargs: Process())
    with pytest.raises(CadPreviewError, match='crash'):
        TubeNotchPreviewJob().run(document(), 'tube_front', 'housing_front')


def test_cancel_running_worker(monkeypatch):
    from threading import Event, Thread

    from suspensionlab.core import cad_tube_notch_job

    started, killed = Event(), Event()
    class Process:
        def wait(self, timeout=None):
            started.set()
            assert killed.wait(3)
            return -1
        def kill(self):
            killed.set()
        def poll(self):
            return None
    monkeypatch.setattr(cad_tube_notch_job.subprocess, 'Popen', lambda *args, **kwargs: Process())
    job, errors = TubeNotchPreviewJob(), []
    def run():
        try:
            job.run(document(), 'tube_front', 'housing_front')
        except CadPreviewError as error:
            errors.append(error.code)
    thread = Thread(target=run)
    thread.start()
    try:
        assert started.wait(3)
        job.cancel()
    finally:
        killed.set()
        thread.join(5)
    assert not thread.is_alive() and errors == ['cancelled']


def test_isolated_plate_preview_and_missing_plate():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.model.scheme_arm_assembly import make_plate, set_assembly_plate

    doc = document()
    with pytest.raises(CadPreviewError, match='missing_plate'):
        TubeNotchPreviewJob().run(doc, 'tube_front', 'ball_plate', timeout=60)
    doc = set_assembly_plate(doc, make_plate(60, 60, 5, 9.5),
                             {'normal': 'z', 'offset_mm': [0, 0, 0]})
    original = deepcopy(doc)
    result = TubeNotchPreviewJob().run(doc, 'tube_front', 'ball_plate', timeout=60)
    assert result.before.bounds_mm == result.after.bounds_mm
    assert all(result.before.views) and all(result.after.views)
    assert any(a != b for a, b in zip(result.before.views, result.after.views, strict=True))
    assert doc == original
    no_overlap = set_assembly_plate(doc, make_plate(60, 60, 5, 5),
                                    {'normal': 'y', 'offset_mm': [0, 100, 0]})
    split = set_assembly_plate(doc, make_plate(60, 60, 5, 5),
                               {'normal': 'y', 'offset_mm': [0, -50, 0]})
    for candidate, reason in ((no_overlap, 'no_overlap'), (split, 'empty_or_split')):
        with pytest.raises(CadPreviewError, match=reason):
            TubeNotchPreviewJob().run(candidate, 'tube_front', 'ball_plate', timeout=60)
