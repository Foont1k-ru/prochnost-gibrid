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
    valid = {'before': projection(), 'after': projection(),
             'tube_before': projection(), 'tube_after': projection(), 'radial_clearance_mm': 0.}
    result = parse_notch_preview(valid)
    assert result.before.bounds_mm == result.after.bounds_mm
    assert result.tube_before.bounds_mm == result.tube_after.bounds_mm
    bad_bounds = projection()
    bad_bounds['bounds_mm'] = [0, 0, 0, 2, 1, 1]
    bad_lines = projection()
    bad_lines['views']['XY'] = [[0, 0, 1, float('nan')]]
    for data in ({}, {'before': projection()}, {**valid, 'extra': 1},
                 {**valid, 'after': bad_bounds}, {**valid, 'after': bad_lines},
                 {**valid, 'tube_after': bad_bounds}, {**valid, 'tube_after': bad_lines},
                 {**valid, 'radial_clearance_mm': True}, {**valid, 'radial_clearance_mm': float('nan')},
                 {**valid, 'radial_clearance_mm': 0.2}):
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
        output, report = Path(command[-5]), Path(command[-4])
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
    assert result.tube_before.bounds_mm == result.tube_after.bounds_mm
    assert all(len(lines) > 0 for lines in (result.before.views + result.after.views +
                                            result.tube_before.views + result.tube_after.views))
    assert any(a != b for a, b in zip(result.before.views, result.after.views, strict=True))
    assert any(a != b for a, b in zip(result.tube_before.views, result.tube_after.views, strict=True))
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
    assert result.tube_before.bounds_mm == result.tube_after.bounds_mm
    assert all(result.before.views) and all(result.after.views)
    assert all(result.tube_before.views) and all(result.tube_after.views)
    assert any(a != b for a, b in zip(result.before.views, result.after.views, strict=True))
    assert any(a != b for a, b in zip(result.tube_before.views, result.tube_after.views, strict=True))
    assert doc == original
    no_overlap = set_assembly_plate(doc, make_plate(60, 60, 5, 5),
                                    {'normal': 'y', 'offset_mm': [0, 100, 0]})
    split = set_assembly_plate(doc, make_plate(60, 60, 5, 5),
                               {'normal': 'y', 'offset_mm': [0, -50, 0]})
    for candidate, reason in ((no_overlap, 'no_overlap'), (split, 'empty_or_split')):
        with pytest.raises(CadPreviewError, match=reason):
            TubeNotchPreviewJob().run(candidate, 'tube_front', 'ball_plate', timeout=60)


def test_tube_self_cut_is_rejected_without_starting_process(monkeypatch):
    from suspensionlab.core import cad_tube_notch_job

    def forbidden(*args, **kwargs):
        raise AssertionError('same-tube cut must not start a worker')
    monkeypatch.setattr(cad_tube_notch_job.subprocess, 'Popen', forbidden)
    for tube in ('tube_front', 'tube_rear'):
        with pytest.raises(CadPreviewError, match='same_tube'):
            TubeNotchPreviewJob().run(document(), tube, tube)


@pytest.mark.parametrize(('tube', 'cutter'), [('tube_front', 'tube_rear'), ('tube_rear', 'tube_front')])
def test_isolated_tube_to_tube_preview(tube, cutter):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    doc = document()
    original = deepcopy(doc)
    result = TubeNotchPreviewJob().run(doc, tube, cutter, timeout=60)
    assert result.before.bounds_mm == result.after.bounds_mm
    assert result.tube_before.bounds_mm == result.tube_after.bounds_mm
    assert all(result.before.views) and all(result.after.views)
    assert all(result.tube_before.views) and all(result.tube_after.views)
    assert any(a != b for a, b in zip(result.before.views, result.after.views, strict=True))
    assert any(a != b for a, b in zip(result.tube_before.views, result.tube_after.views, strict=True))
    assert doc == original


def test_isolated_tube_to_tube_refuses_butt_contact():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    project = Project.create_default()
    for code, xyz in {'lca_f_in': (0, 0, 0), 'lca_r_in': (0, 200, 0), 'lbj': (0, 100, 0)}.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    doc = make_scheme_arm_assembly(project, 10, 2, {'axis': 'x', 'outer_radius_mm': 14,
                                                      'bore_radius_mm': 7, 'length_mm': 24})
    with pytest.raises(CadPreviewError, match='no_overlap'):
        TubeNotchPreviewJob().run(doc, 'tube_front', 'tube_rear', timeout=60)


def test_hidden_plate_cut_can_be_inspected_as_tube_only():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.model.scheme_arm_assembly import make_plate, set_assembly_plate

    doc = set_assembly_plate(document(), make_plate(60, 60, 5, 9.5),
                             {'normal': 'y', 'offset_mm': [0, 0, 0]})
    before = deepcopy(doc)
    result = TubeNotchPreviewJob().run(doc, 'tube_front', 'ball_plate', timeout=60)
    assert doc == before
    assert result.tube_before.bounds_mm == result.tube_after.bounds_mm
    # Independent expected bounds of the original front tube.
    assert result.tube_before.bounds_mm == pytest.approx((-10, 0, -10, 10, 100, 10), abs=1e-6)
    assert any(a != b for a, b in zip(result.tube_before.views, result.tube_after.views, strict=True))
    # The comparison is genuinely for different displayed shapes, not the pair again.
    assert result.before.bounds_mm != result.tube_before.bounds_mm


def test_clearance_validation_is_preflight_and_housing_only(monkeypatch):
    from suspensionlab.core import cad_tube_notch_job

    def forbidden(*args, **kwargs):
        raise AssertionError('invalid clearance must not start worker')
    monkeypatch.setattr(cad_tube_notch_job.subprocess, 'Popen', forbidden)
    for invalid in (-1, 100.001, float('nan'), float('inf'), float('-inf'), True, '1', None, 10**400):
        with pytest.raises(CadPreviewError, match='invalid_clearance'):
            TubeNotchPreviewJob().run(document(), 'tube_front', 'housing_front', radial_clearance_mm=invalid)
    for cutter in ('ball_plate', 'tube_rear'):
        with pytest.raises(CadPreviewError, match='invalid_clearance'):
            TubeNotchPreviewJob().run(document(), 'tube_front', cutter, radial_clearance_mm=1)


def test_preview_result_must_echo_requested_clearance():
    valid = {'before': projection(), 'after': projection(), 'tube_before': projection(),
             'tube_after': projection(), 'radial_clearance_mm': 1.25}
    assert parse_notch_preview(valid, expected_clearance_mm=1.25)
    for returned in (0, 2, True, '1.25', float('inf'), float('nan')):
        with pytest.raises(CadPreviewError, match='output'):
            parse_notch_preview({**valid, 'radial_clearance_mm': returned}, expected_clearance_mm=1.25)


def test_worker_refuses_invalid_or_unsupported_clearance_without_output(tmp_path):
    import json
    import os
    import sys

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.model.kim_format import write_document

    source, output, report = tmp_path / 'in.kima', tmp_path / 'out.json', tmp_path / 'report.json'
    write_document(source, 'assembly', document())
    for cutter, gap in [('housing_front', '-1'), ('housing_front', 'nan'), ('housing_front', 'bad'),
                        ('housing_front', '101'), ('ball_plate', '1'), ('tube_rear', '1')]:
        process = subprocess.run([sys.executable, '-m', 'suspensionlab.core.cad_tube_notch_worker',
                                  str(source), str(output), str(report), 'tube_front', cutter, gap],
                                 env=os.environ.copy(), capture_output=True, timeout=30, check=False)
        assert process.returncode != 0 and not output.exists()
        assert json.loads(report.read_text(encoding='utf-8')) == {'status': 'error', 'code': 'invalid_clearance'}


def test_real_isolated_preview_changes_with_housing_clearance():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    doc = document()
    original = deepcopy(doc)
    zero = TubeNotchPreviewJob().run(doc, 'tube_front', 'housing_front', radial_clearance_mm=0, timeout=90)
    clearance = TubeNotchPreviewJob().run(doc, 'tube_front', 'housing_front', radial_clearance_mm=2, timeout=90)
    assert zero.before == clearance.before and zero.tube_before == clearance.tube_before
    assert zero.tube_after.bounds_mm == clearance.tube_after.bounds_mm
    assert zero.tube_after.views != clearance.tube_after.views
    assert doc == original
