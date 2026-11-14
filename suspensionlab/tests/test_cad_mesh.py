"""Численные проверки визуальной сетки, не инженерной точности CAD."""
from threading import Event

import numpy as np
import pytest

from suspensionlab.core.cad_mesh import MAX_COORDINATE, MAX_TRIANGLES, CadMesh, project_triangles
from suspensionlab.core.cad_transport import CadJob, CadPreviewError


def test_mesh_copies_bounds_and_projection():
    data = np.array([[[0, 0, 0], [2, 0, 0], [0, 2, 0]], [[0, 0, 3], [2, 0, 3], [0, 2, 3]]], dtype=float)
    mesh = CadMesh(data, 2)
    data[0, 0, 0] = 999
    assert mesh.triangles[0, 0, 0] == 0 and not mesh.triangles.flags.writeable
    center, radius = mesh.bounds()
    assert center == pytest.approx((1, 1, 1.5)) and radius == pytest.approx(np.sqrt(4.25))
    projected, order = project_triangles(mesh, 0, 0)
    assert projected.shape == (2, 3, 2) and set(order) == {0, 1}
    assert projected[0, 0] == pytest.approx((-1, -1.5))
    for yaw, elevation in ((0, 0), (1, 0.8), (-2, -1)):
        coords, _ = project_triangles(mesh, yaw, elevation)
        assert np.max(np.linalg.norm(coords, axis=2)) <= radius + 1e-8
    with pytest.raises(ValueError):
        project_triangles(mesh, float("nan"), 0)


@pytest.mark.parametrize("triangles,faces", [
    (np.zeros((0, 3, 3)), 1),
    (np.zeros((1, 3, 2)), 1),
    (np.full((1, 3, 3), float("nan")), 1),
    (np.full((1, 3, 3), MAX_COORDINATE + 1), 1),
    (np.zeros((1, 3, 3)), 0),
    (np.zeros((MAX_TRIANGLES + 1, 3, 3)), 1),
])
def test_bad_or_oversized_mesh_rejected(triangles, faces):
    with pytest.raises(ValueError):
        CadMesh(triangles, faces)


def test_cancel_before_start_and_invalid_file(tmp_path):
    job = CadJob()
    job.cancel()
    with pytest.raises(CadPreviewError, match="cancelled"):
        job.run(tmp_path / "not-found", 2)
    job = CadJob()
    with pytest.raises(CadPreviewError, match="file_size"):
        job.run(tmp_path / "not-found", 2, timeout=15)


def test_timeout_kills_child(monkeypatch, tmp_path):
    import subprocess

    from suspensionlab.core import cad_transport

    killed = Event()
    class DummyProcess:
        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("worker", timeout)
            return 1
        def kill(self):
            killed.set()
    monkeypatch.setattr(cad_transport.subprocess, "Popen", lambda *args, **kwargs: DummyProcess())
    with pytest.raises(CadPreviewError, match="timeout"):
        CadJob().run(tmp_path / "not-found", 2, timeout=0.1)
    assert killed.is_set()
