"""Транспорт, изоляция и проверка предварительного просмотра последовательности."""
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from threading import Event, Thread

import pytest

from suspensionlab.core.cad_transport import CadPreviewError
from suspensionlab.core.cad_tube_notch_sequence_job import (
    SequencePreviewError,
    SequencePreviewJob,
    parse_sequence_preview,
)
from suspensionlab.model.entities import Project
from suspensionlab.model.scheme_arm_assembly import make_plate, make_scheme_arm_assembly, set_assembly_plate


def document(rear=(100, 100, 0), plate=True):
    project = Project.create_default()
    for code, xyz in {'lca_f_in': (0, 0, 0), 'lca_r_in': rear, 'lbj': (0, 100, 0)}.items():
        point = project.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    doc = make_scheme_arm_assembly(project, 10, 2, {'axis': 'x', 'outer_radius_mm': 14,
                                                     'bore_radius_mm': 7, 'length_mm': 24})
    return (set_assembly_plate(doc, make_plate(60, 60, 5, 9.5),
                               {'normal': 'z', 'offset_mm': [0, -30, 0]}) if plate else doc)


def projection():
    return {'views': {key: [[0, 0, 1, 1]] for key in ('XY', 'XZ', 'YZ')},
            'bounds_mm': [0, 0, 0, 1, 1, 1]}


def test_parser_rejects_malformed_inconsistent_or_unsafe_results():
    valid = {'before': projection(), 'after': projection()}
    result = parse_sequence_preview(valid)
    assert result.before.bounds_mm == result.after.bounds_mm
    bad_bounds = projection()
    bad_bounds['bounds_mm'] = [0, 0, 0, 2, 1, 1]
    bad_lines = projection()
    bad_lines['views']['XY'] = [[0, 0, float('nan'), 1]]
    outside = projection()
    outside['views']['XY'] = [[0, 0, 99, 1]]
    too_many = projection()
    too_many['views']['XY'] = [[0, 0, 1, 1]] * 30001
    for value in ({}, {'before': projection()}, {**valid, 'extra': 1},
                  {**valid, 'after': bad_bounds}, {**valid, 'after': bad_lines},
                  {**valid, 'after': outside}, {**valid, 'after': too_many}):
        with pytest.raises(CadPreviewError, match='output'):
            parse_sequence_preview(value)


def test_preflight_prevents_invalid_steps_without_process(monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence_job

    def forbidden(*args, **kwargs):
        raise AssertionError('worker must not start')
    monkeypatch.setattr(cad_tube_notch_sequence_job.subprocess, 'Popen', forbidden)
    with pytest.raises(SequencePreviewError, match='missing_plate') as error:
        SequencePreviewJob().run(document(plate=False), 'tube_front', ['housing_front', 'ball_plate'])
    assert (error.value.step_index, error.value.cutter_id) == (1, 'ball_plate')
    with pytest.raises(SequencePreviewError, match='same_tube'):
        SequencePreviewJob().run(document(), 'tube_front', ['tube_front'])
    with pytest.raises(SequencePreviewError, match='duplicate_cutter'):
        SequencePreviewJob().run(document(), 'tube_front', ['housing_front', 'housing_front'])
    with pytest.raises(CadPreviewError, match='invalid_sequence'):
        SequencePreviewJob().run(document(), 'tube_front', [])
    job = SequencePreviewJob()
    job.cancel()
    with pytest.raises(CadPreviewError, match='cancelled'):
        job.run(document(), 'tube_front', ['housing_front'])


def test_reports_are_untrusted_and_must_match_requested_step(monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence_job

    state = {}
    class Process:
        def wait(self, timeout=None):
            return 1
    def start(command, **kwargs):
        report = Path(command[-4])  # 2 cutters: report is followed by tube, cutter, cutter.
        report.write_text(json.dumps(state), encoding='utf-8')
        return Process()
    monkeypatch.setattr(cad_tube_notch_sequence_job.subprocess, 'Popen', start)
    doc = document()
    order = ['housing_front', 'tube_rear']
    for report in ({'status': 'error', 'code': 'no_overlap', 'step': True, 'cutter': 'tube_rear'},
                   {'status': 'error', 'code': 'no_overlap', 'step': 99, 'cutter': 'tube_rear'},
                   {'status': 'error', 'code': 'no_overlap', 'step': 1, 'cutter': 'housing_front'},
                   {'status': 'error', 'code': 'no_overlap', 'step': 1},
                   {'status': 'ok'}):
        state.clear()
        state.update(report)
        with pytest.raises(CadPreviewError):
            SequencePreviewJob().run(doc, 'tube_front', order)
    state.clear()
    state.update({'status': 'error', 'code': 'no_overlap', 'step': 1, 'cutter': 'tube_rear'})
    with pytest.raises(SequencePreviewError, match='no_overlap') as error:
        SequencePreviewJob().run(doc, 'tube_front', order)
    assert (error.value.step_index, error.value.cutter_id) == (1, 'tube_rear')


def test_success_report_with_malformed_output_is_rejected(monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence_job

    class Process:
        def wait(self, timeout=None):
            return 0
    def start(command, **kwargs):
        Path(command[-3]).write_text('{"status":"ok"}', encoding='utf-8')
        Path(command[-4]).write_text('{}', encoding='utf-8')
        return Process()
    monkeypatch.setattr(cad_tube_notch_sequence_job.subprocess, 'Popen', start)
    with pytest.raises(CadPreviewError, match='output'):
        SequencePreviewJob().run(document(), 'tube_front', ['housing_front'])


def test_timeout_kills_and_reaps(monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence_job

    class Process:
        killed = False
        waits = 0
        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired('sequence', timeout)
            return -1
        def kill(self):
            self.killed = True
    process = Process()
    monkeypatch.setattr(cad_tube_notch_sequence_job.subprocess, 'Popen', lambda *args, **kwargs: process)
    with pytest.raises(CadPreviewError, match='timeout'):
        SequencePreviewJob().run(document(), 'tube_front', ['housing_front'], timeout=.01)
    assert process.killed and process.waits == 2


def test_running_worker_can_be_cancelled(monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence_job

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
    monkeypatch.setattr(cad_tube_notch_sequence_job.subprocess, 'Popen', lambda *args, **kwargs: Process())
    job, errors = SequencePreviewJob(), []
    def run():
        try:
            job.run(document(), 'tube_front', ['housing_front'])
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


@pytest.mark.parametrize(('tube', 'order'), [
    ('tube_front', ['housing_front', 'ball_plate', 'tube_rear']),
    ('tube_rear', ['housing_rear', 'ball_plate', 'tube_front']),
])
def test_isolated_real_cad_process_projects_complete_sequence(tube, order):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    doc = document()
    before, original_order = deepcopy(doc), list(order)
    result = SequencePreviewJob().run(doc, tube, order, timeout=120)
    assert result.before.bounds_mm == result.after.bounds_mm
    assert all(result.before.views) and all(result.after.views)
    assert any(a != b for a, b in zip(result.before.views, result.after.views, strict=True))
    assert doc == before and order == original_order


def test_isolated_process_reports_later_cut_failure():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    doc = document(rear=(1, 0, 0))
    original = deepcopy(doc)
    with pytest.raises(SequencePreviewError, match='no_overlap') as error:
        SequencePreviewJob().run(doc, 'tube_front', ['housing_front', 'housing_rear'], timeout=120)
    assert (error.value.step_index, error.value.cutter_id) == (1, 'housing_rear')
    assert not hasattr(error.value, 'before') and doc == original


def test_worker_crash_without_report(monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence_job

    class Process:
        def wait(self, timeout=None):
            return 1
    monkeypatch.setattr(cad_tube_notch_sequence_job.subprocess, 'Popen', lambda *args, **kwargs: Process())
    with pytest.raises(CadPreviewError, match='crash'):
        SequencePreviewJob().run(document(), 'tube_front', ['housing_front'])
