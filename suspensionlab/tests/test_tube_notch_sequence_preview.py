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
    order = ('housing_front', 'tube_rear')
    def stage(cutter, initial, remaining):
        return {'cutter': cutter, 'projection': projection(), 'pair_before': projection(), 'pair_after': projection(),
                'input_volume_mm3': initial, 'remaining_volume_mm3': remaining,
                'removed_volume_mm3': initial - remaining}
    valid = {'before': projection(), 'stages': [stage(order[0], .9, .7), stage(order[1], .7, .5)]}
    result = parse_sequence_preview(valid, order)
    assert result.before.bounds_mm == result.after.bounds_mm
    assert tuple(x.cutter_id for x in result.stages) == order
    assert result.stages[0].input_volume_mm3 == .9 and result.stages[1].remaining_volume_mm3 == .5
    invalid = [{}, {'before': projection()}, {**valid, 'extra': 1},
               {**valid, 'stages': []}, {**valid, 'stages': list(reversed(valid['stages']))},
               {**valid, 'stages': [*valid['stages'], valid['stages'][0]]}]
    for key in ('projection', 'pair_before', 'pair_after'):
        bad_bounds = deepcopy(valid)
        bad_bounds['stages'][1][key]['bounds_mm'] = [0, 0, 0, 2, 1, 1]
        invalid.append(bad_bounds)
        for coordinate in (float('nan'), 99):
            bad_lines = deepcopy(valid)
            bad_lines['stages'][1][key]['views']['XY'] = [[0, 0, coordinate, 1]]
            invalid.append(bad_lines)
        extra = deepcopy(valid)
        extra['stages'][1].pop(key)
        invalid.append(extra)
    for key in ('input_volume_mm3', 'remaining_volume_mm3', 'removed_volume_mm3'):
        for value in (True, None, '0.1', 0, -1, float('nan'), float('inf'), 10**400, 2):
            bad = deepcopy(valid)
            bad['stages'][1][key] = value
            invalid.append(bad)
        missing = deepcopy(valid)
        del missing['stages'][1][key]
        invalid.append(missing)
    mismatch = deepcopy(valid)
    mismatch['stages'][1]['removed_volume_mm3'] = .01
    invalid.append(mismatch)
    mismatch = deepcopy(valid)
    mismatch['stages'][1].update(input_volume_mm3=.8, remaining_volume_mm3=.5, removed_volume_mm3=.3)
    invalid.append(mismatch)
    mismatch = deepcopy(valid)
    mismatch['stages'][1].update(input_volume_mm3=.5, remaining_volume_mm3=.7, removed_volume_mm3=.2)
    invalid.append(mismatch)
    too_many = deepcopy(valid)
    too_many['stages'][1]['pair_after']['views']['XY'] = [[0, 0, 1, 1]] * 30001
    invalid.append(too_many)
    for value in invalid:
        with pytest.raises(CadPreviewError, match='output'):
            parse_sequence_preview(value, order)
    with pytest.raises(CadPreviewError, match='output'):
        parse_sequence_preview(valid, ())


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


@pytest.mark.parametrize(('tube', 'order', 'rear'), [
    ('tube_front', ['housing_front', 'ball_plate', 'tube_rear'], (100, 100, 0)),
    ('tube_rear', ['housing_rear', 'ball_plate', 'tube_front'], (100, 100, 0)),
    ('tube_front', ['housing_front', 'housing_rear', 'ball_plate', 'tube_rear'], (20, 50, 0)),
])
def test_isolated_real_cad_process_projects_complete_sequence(tube, order, rear):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    doc = document(rear=rear)
    before, original_order = deepcopy(doc), list(order)
    result = SequencePreviewJob().run(doc, tube, order, timeout=240)
    assert result.before.bounds_mm == result.after.bounds_mm
    assert [stage.cutter_id for stage in result.stages] == order
    assert all(stage.projection.bounds_mm == result.before.bounds_mm for stage in result.stages)
    assert all(all(stage.projection.views) for stage in result.stages)
    assert all(stage.pair_before.bounds_mm == stage.pair_after.bounds_mm for stage in result.stages)
    assert all(stage.input_volume_mm3 > stage.remaining_volume_mm3 > 0 and
               stage.removed_volume_mm3 == pytest.approx(stage.input_volume_mm3 - stage.remaining_volume_mm3)
               for stage in result.stages)
    assert all(a.remaining_volume_mm3 == pytest.approx(b.input_volume_mm3, rel=1e-8)
               for a, b in zip(result.stages, result.stages[1:], strict=False))
    assert all(all(stage.pair_before.views) and all(stage.pair_after.views) for stage in result.stages)
    assert all(result.before.views) and all(result.after.views)
    assert any(a != b for a, b in zip(result.before.views, result.after.views, strict=True))
    if tube == 'tube_front' and rear == (100, 100, 0):
        from suspensionlab.core.cad_tube_notch_job import TubeNotchPreviewJob

        single = TubeNotchPreviewJob().run(doc, tube, 'housing_front', timeout=120)
        assert result.stages[0].pair_before.bounds_mm == pytest.approx(single.before.bounds_mm, abs=1e-6)
        assert result.stages[0].pair_after.bounds_mm == pytest.approx(single.after.bounds_mm, abs=1e-6)
        assert [len(v) for v in result.stages[0].pair_before.views] == [len(v) for v in single.before.views]
        assert [len(v) for v in result.stages[0].pair_after.views] == [len(v) for v in single.after.views]
        # Independently build the first cut and add the second cutter (plate).
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        from suspensionlab.core.cad_assembly_projection import bounds_for_shape, project_shape
        from suspensionlab.core.cad_assembly_projection_job import parse_projection
        from suspensionlab.core.cad_kim_prototype import _place_scheme_arm_plate
        from suspensionlab.core.cad_tube_notch import notch_tube_against_housing

        first_cut = notch_tube_against_housing(doc, tube, 'housing_front')
        assert result.stages[0].input_volume_mm3 == pytest.approx(first_cut.original_volume_mm3, rel=1e-8)
        assert result.stages[0].remaining_volume_mm3 == pytest.approx(first_cut.remaining_volume_mm3, rel=1e-8)
        assert result.stages[0].removed_volume_mm3 == pytest.approx(first_cut.removed_volume_mm3, rel=1e-8)
        builder, pair = BRep_Builder(), TopoDS_Compound()
        builder.MakeCompound(pair)
        builder.Add(pair, first_cut.shape)
        builder.Add(pair, _place_scheme_arm_plate(doc))
        expected = parse_projection({'views': project_shape(pair), 'bounds_mm': bounds_for_shape(pair)})
        assert result.stages[1].pair_before == expected
        assert result.stages[1].pair_after != expected
    assert doc == before and order == original_order


def test_isolated_process_reports_later_cut_failure():
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    doc = document(rear=(1, 0, 0))
    original = deepcopy(doc)
    with pytest.raises(SequencePreviewError, match='no_overlap') as error:
        SequencePreviewJob().run(doc, 'tube_front', ['housing_front', 'housing_rear'], timeout=240)
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


def test_worker_writes_no_partial_stages_when_later_cut_fails(tmp_path):
    import sys

    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.model.kim_format import write_document

    source, output, report = (tmp_path / 'snapshot.kima', tmp_path / 'preview.json', tmp_path / 'report.json')
    write_document(source, 'assembly', document(rear=(1, 0, 0)), overwrite=False)
    process = subprocess.run([sys.executable, '-m', 'suspensionlab.core.cad_tube_notch_sequence_worker',
                              str(source), str(output), str(report), 'tube_front', 'housing_front', 'housing_rear'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False)
    assert process.returncode != 0 and not output.exists()
    assert json.loads(report.read_text(encoding='utf-8')) == {
        'status': 'error', 'code': 'no_overlap', 'step': 1, 'cutter': 'housing_rear'}


def test_sequence_parser_limits_total_segments_across_pairs():
    order = ('housing_front', 'tube_rear')
    many = {'views': {'XY': [[0, 0, 1, 1]] * 25000,
                      'XZ': [[0, 0, 1, 1]], 'YZ': [[0, 0, 1, 1]]},
            'bounds_mm': [0, 0, 0, 1, 1, 1]}
    value = {'before': many, 'stages': [
        {'cutter': cutter, 'projection': many, 'pair_before': many, 'pair_after': many,
         'input_volume_mm3': initial, 'remaining_volume_mm3': remaining, 'removed_volume_mm3': initial - remaining}
        for cutter, initial, remaining in zip(order, (.9, .7), (.7, .5), strict=True)]}
    with pytest.raises(CadPreviewError, match='output'):
        parse_sequence_preview(value, order)


def test_oversized_worker_output_is_rejected_before_reading(monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence_job

    class Process:
        def wait(self, timeout=None):
            return 0
    def start(command, **kwargs):
        Path(command[-3]).write_text('{"status":"ok"}', encoding='utf-8')
        Path(command[-4]).write_text(' ' * 100, encoding='utf-8')
        return Process()
    monkeypatch.setattr(cad_tube_notch_sequence_job, 'MAX_SEQUENCE_BYTES', 50)
    monkeypatch.setattr(cad_tube_notch_sequence_job.subprocess, 'Popen', start)
    with pytest.raises(CadPreviewError, match='output'):
        SequencePreviewJob().run(document(), 'tube_front', ['housing_front'])


def test_worker_rejects_oversized_payload_without_writing_output(tmp_path, monkeypatch):
    from suspensionlab.core import cad_tube_notch_sequence_preview, cad_tube_notch_sequence_worker

    monkeypatch.setattr(cad_tube_notch_sequence_worker, 'read_document', lambda *args: {})
    monkeypatch.setattr(cad_tube_notch_sequence_preview, 'project_notch_sequence', lambda *args: {'large': 'x' * 100})
    monkeypatch.setattr(cad_tube_notch_sequence_worker, 'MAX_SEQUENCE_BYTES', 50)
    output, report = tmp_path / 'output', tmp_path / 'report'
    assert cad_tube_notch_sequence_worker.main(['source', str(output), str(report), 'tube_front', 'housing_front']) == 1
    assert not output.exists() and json.loads(report.read_text()) == {'status': 'error', 'code': 'limit'}


def test_projection_stops_when_total_segment_budget_exceeded(monkeypatch):
    pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)
    from suspensionlab.core import cad_tube_notch_sequence_preview
    from suspensionlab.core.cad_worker import CadWorkerError

    calls = []
    def project(shape):
        calls.append(shape)
        return {key: [[0, 0, 1, 1]] for key in ('XY', 'XZ', 'YZ')}
    monkeypatch.setattr(cad_tube_notch_sequence_preview, 'project_shape', project)
    monkeypatch.setattr(cad_tube_notch_sequence_preview, 'MAX_SEQUENCE_SEGMENTS', 4)
    with pytest.raises(CadWorkerError, match='limit'):
        cad_tube_notch_sequence_preview.project_notch_sequence(document(), 'tube_front', ['housing_front'])
    assert len(calls) == 2
