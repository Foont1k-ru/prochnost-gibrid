"""Cancellation after child exit while the untrusted mesh is still being read."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from suspensionlab.core import cad_transport
from suspensionlab.core.cad_transport import CadJob, CadPreviewError


@pytest.fixture
def finished_child(monkeypatch):
    paths = []

    class Process:
        def wait(self, timeout=None):
            return 0

    def spawn(command, **_kwargs):
        output, report = Path(command[-3]), Path(command[-2])
        np.savez(output, triangles=np.zeros((100, 3, 3)), faces=np.array([1]), skipped=np.array([0]),
                 recovered=np.array([0]), names=np.array(['part']), groups=np.zeros(100, dtype=np.int32),
                 instance_groups=np.array([0]), instances=np.zeros(100, dtype=np.int32))
        report.write_text(json.dumps({'status': 'ok'}), encoding='utf-8')
        paths.append(output)
        return Process()

    monkeypatch.setattr(cad_transport.subprocess, 'Popen', spawn)
    return paths


def run_cancelling(job, entered, release, source):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(job.run, source, 2.)
        try:
            assert entered.wait(10), 'reader never reached test barrier'
            job.cancel()
        finally:
            release.set()
        with pytest.raises(CadPreviewError, match='cancelled'):
            future.result(timeout=10)


def test_cancel_after_zip_check_skips_numpy_load(monkeypatch, tmp_path, finished_child):
    entered, release = Event(), Event()
    original = cad_transport.zipfile.ZipFile.infolist
    load_called = []

    def slow_list(archive):
        result = original(archive)
        entered.set()
        assert release.wait(10)
        return result

    def unexpected_load(*_a, **_kw):
        load_called.append(True)
        raise AssertionError('numpy must not load a cancelled result')

    monkeypatch.setattr(cad_transport.zipfile.ZipFile, 'infolist', slow_list)
    monkeypatch.setattr(cad_transport.np, 'load', unexpected_load)
    run_cancelling(CadJob(), entered, release, tmp_path / 'source.step')
    assert not load_called and finished_child and not finished_child[0].exists()


@pytest.mark.parametrize('blocked_key', ['instance_groups', 'triangles'])
def test_cancel_while_reading_arrays_skips_mesh(monkeypatch, tmp_path, finished_child, blocked_key):
    entered, release = Event(), Event()
    original_load = cad_transport.np.load
    mesh_called = []
    read_keys = []

    class Reader:
        def __init__(self, reader):
            self.reader = reader

        def __enter__(self):
            self.reader.__enter__()
            return self

        def __exit__(self, *args):
            return self.reader.__exit__(*args)

        def __getitem__(self, key):
            read_keys.append(key)
            value = self.reader[key]
            if key == blocked_key:
                entered.set()
                assert release.wait(10)
            return value

    def load(*args, **kwargs):
        return Reader(original_load(*args, **kwargs))

    def no_mesh(*_a, **_kw):
        mesh_called.append(True)
        raise AssertionError('must not build a cancelled mesh')

    monkeypatch.setattr(cad_transport.np, 'load', load)
    monkeypatch.setattr(cad_transport, 'CadMesh', no_mesh)
    run_cancelling(CadJob(), entered, release, tmp_path / 'source.step')
    assert not mesh_called and finished_child and not finished_child[0].exists()
    assert 'groups' not in read_keys and 'instances' not in read_keys


def test_cancel_while_validating_mesh_never_returns_result(monkeypatch, tmp_path, finished_child):
    entered, release = Event(), Event()
    original = cad_transport.CadMesh

    def blocked_mesh(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(cad_transport, 'CadMesh', blocked_mesh)
    run_cancelling(CadJob(), entered, release, tmp_path / 'source.step')
    assert finished_child and not finished_child[0].exists()


def test_io_error_after_cancellation_reports_cancelled(monkeypatch, tmp_path, finished_child):
    entered, release = Event(), Event()

    def blocked_load(*_args, **_kwargs):
        entered.set()
        assert release.wait(10)
        raise OSError('reader failed')

    monkeypatch.setattr(cad_transport.np, 'load', blocked_load)
    run_cancelling(CadJob(), entered, release, tmp_path / 'source.step')
    assert finished_child and not finished_child[0].exists()


def test_bad_result_without_cancellation_is_still_rejected(monkeypatch, tmp_path, finished_child):
    def broken_load(*_args, **_kwargs):
        raise OSError('reader failed')

    monkeypatch.setattr(cad_transport.np, 'load', broken_load)
    with pytest.raises(CadPreviewError, match='output'):
        CadJob().run(tmp_path / 'source.step', 2.)
    assert finished_child and not finished_child[0].exists()
