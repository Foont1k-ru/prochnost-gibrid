from pathlib import Path

import numpy as np
import pytest

from suspensionlab.core.cad_cache import CadMeshCache, Fingerprint, fingerprint, mesh_bytes
from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_transport import CadJob, CadPreviewError


def mesh(value=1.):
    return CadMesh(np.full((1, 3, 3), value), 1)


def test_reuses_only_matching_content_quality_and_force(tmp_path, monkeypatch):
    source = tmp_path / 'model.step'
    source.write_bytes(b'first model')
    calls = []
    def build(self, path, deviation):
        calls.append((path, deviation))
        return mesh(deviation)
    monkeypatch.setattr(CadJob, 'run', build)
    cache = CadMeshCache()
    first, hit = cache.run(CadJob(), source, 2.)
    assert not hit and len(calls) == 1
    second, hit = cache.run(CadJob(), source, 2.)
    assert hit and first is second and len(calls) == 1
    _, hit = cache.run(CadJob(), source, 0.2)
    assert not hit and len(calls) == 2
    _, hit = cache.run(CadJob(), source, 2., force=True)
    assert not hit and len(calls) == 3
    # Same length and restored mtime are insufficient to reuse changed content.
    import os
    old = source.stat()
    source.write_bytes(b'other model')
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
    _, hit = cache.run(CadJob(), source, 2.)
    assert not hit and len(calls) == 4


def test_lru_budget_and_oversized_mesh():
    m = mesh()
    budget = mesh_bytes(m) * 2
    cache = CadMeshCache(budget)
    def key(i):
        return Fingerprint(str(i), bytes([i])), 2.
    cache.put(key(1), m)
    cache.put(key(2), m)
    assert cache.get(key(1)) is m
    cache.put(key(3), m)
    assert cache.get(key(2)) is None and cache.get(key(1)) is m and cache.get(key(3)) is m
    oversized = CadMesh(np.zeros((3, 3, 3)), 1)
    cache.put(key(3), oversized)
    assert cache.get(key(3)) is None and cache._bytes == mesh_bytes(m)


def test_file_changed_during_build_rejected_and_not_cached(tmp_path, monkeypatch):
    source = tmp_path / 'file.step'
    source.write_bytes(b'old')
    def build(self, path, deviation):
        path.write_bytes(b'new')
        return mesh()
    monkeypatch.setattr(CadJob, 'run', build)
    cache = CadMeshCache()
    with pytest.raises(CadPreviewError, match='source_changed'):
        cache.run(CadJob(), source, 2.)
    assert not cache._items


def test_cancellation_before_and_after_meshing(tmp_path, monkeypatch):
    source = tmp_path / 'file.step'
    source.write_bytes(b'content')
    job = CadJob()
    job.cancel()
    with pytest.raises(CadPreviewError, match='cancelled'):
        CadMeshCache().run(job, source, 2.)
    def build(self, path, deviation):
        self.cancel()
        return mesh()
    monkeypatch.setattr(CadJob, 'run', build)
    cache = CadMeshCache()
    with pytest.raises(CadPreviewError, match='cancelled'):
        cache.run(CadJob(), source, 2.)
    assert not cache._items


def test_invalid_file_never_uses_cache(tmp_path, monkeypatch):
    calls = []
    def fail(self, source, deviation):
        calls.append(1)
        raise CadPreviewError('file_size')
    monkeypatch.setattr(CadJob, 'run', fail)
    cache = CadMeshCache()
    for file in (tmp_path / 'missing', tmp_path):
        assert fingerprint(file, lambda: False) is None
        with pytest.raises(CadPreviewError, match='file_size'):
            cache.run(CadJob(), file, 2.)
    assert len(calls) == 2


def test_hashes_path_distinguishes_identical_files(tmp_path):
    one, two = tmp_path / 'a.step', tmp_path / 'b.step'
    one.write_bytes(b'same')
    two.write_bytes(b'same')
    a, b = fingerprint(one, lambda: False), fingerprint(two, lambda: False)
    assert a and b and a.digest == b.digest and a != b
    assert isinstance(Path(a.resolved), Path)


def test_windows_stat_and_fstat_may_have_different_inode_or_ctime(tmp_path):
    from dataclasses import dataclass, replace

    from suspensionlab.core.cad_cache import _stable_stats
    @dataclass
    class Stats:
        st_dev: int = 1
        st_ino: int = 2
        st_size: int = 100
        st_mtime_ns: int = 1000
        st_ctime_ns: int = 2000
    handle = Stats(st_ino=0, st_ctime_ns=100)
    path = Stats()
    assert _stable_stats(handle, handle, path, path, windows=True)
    assert not _stable_stats(handle, handle, path, path, windows=False)
    assert not _stable_stats(handle, replace(handle, st_size=101), path, path, windows=True)
    assert not _stable_stats(handle, handle, path, replace(path, st_mtime_ns=999), windows=True)
    assert not _stable_stats(handle, handle, path, replace(path, st_size=101), windows=True)


def test_verified_fingerprint_is_of_mesh_not_previous_failed_job(tmp_path, monkeypatch):
    from hashlib import sha256
    source = tmp_path / 'model.step'
    source.write_bytes(b'original')
    calls = []
    def build(self, path, deviation):
        calls.append(1)
        return mesh()
    monkeypatch.setattr(CadJob, 'run', build)
    cache = CadMeshCache()
    expected = sha256(b'original').digest()
    _, hit, identity = cache.run_with_fingerprint(CadJob(), source, 2., expected_digest=expected)
    assert not hit and identity and identity.digest == expected
    _, hit, identity = cache.run_with_fingerprint(CadJob(), source, 2., expected_digest=expected)
    assert hit and identity and identity.digest == expected and len(calls) == 1
    source.write_bytes(b'different')
    with pytest.raises(CadPreviewError, match='source_mismatch'):
        cache.run_with_fingerprint(CadJob(), source, 2., expected_digest=expected)
    assert len(calls) == 1  # mismatch is rejected before expensive CAD
    _, hit, identity = cache.run_with_fingerprint(CadJob(), source, 2.)
    assert not hit and identity and identity.digest == sha256(b'different').digest()
    other = tmp_path / 'copy.step'
    other.write_bytes(b'original')
    _, _, identity = cache.run_with_fingerprint(CadJob(), other, 2., expected_digest=expected)
    assert identity and identity.digest == expected  # content equality, not file path equality
    with pytest.raises(CadPreviewError, match='source_mismatch'):
        cache.run_with_fingerprint(CadJob(), tmp_path / 'missing', 2., expected_digest=expected)


def test_fingerprint_not_returned_if_source_changes_during_job(tmp_path, monkeypatch):
    source = tmp_path / 'model.step'
    source.write_bytes(b'original')
    def build(self, path, deviation):
        path.write_bytes(b'changed')
        return mesh()
    monkeypatch.setattr(CadJob, 'run', build)
    cache = CadMeshCache()
    with pytest.raises(CadPreviewError, match='source_changed'):
        cache.run_with_fingerprint(CadJob(), source, 2.)
    assert not cache._items
