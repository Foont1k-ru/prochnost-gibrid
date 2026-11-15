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


def test_skipped_faces_must_fit_total():
    triangles = np.zeros((1, 3, 3))
    mesh = CadMesh(triangles, 4, 2)
    assert mesh.face_count == 4 and mesh.skipped_faces == 2
    for skipped in (-1, 4, 5):
        with pytest.raises(ValueError):
            CadMesh(triangles, 4, skipped)


def test_worker_saves_partial_count(monkeypatch, tmp_path):
    from suspensionlab.core import cad_worker

    source, output, report = (tmp_path / name for name in ("a.step", "mesh.npz", "status.json"))
    monkeypatch.setattr(cad_worker, "create_mesh", lambda path, deviation: (np.zeros((1, 3, 3)), 3, 2, 1, ("неизвестно",), np.array([0]), (0,), np.array([0])))
    assert cad_worker.main([str(source), str(output), str(report), "2"]) == 0
    with np.load(output, allow_pickle=False) as data:
        assert list(data["faces"]) == [3] and list(data["skipped"]) == [2] and list(data["recovered"]) == [1]


def test_transport_preserves_and_validates_missing_faces(monkeypatch, tmp_path):
    import json
    from pathlib import Path

    from suspensionlab.core import cad_transport

    class DummyProcess:
        def wait(self, timeout=None):
            return 0

    def spawn(skipped):
        def run(command, **kwargs):
            output, report = Path(command[-3]), Path(command[-2])
            np.savez_compressed(output, triangles=np.zeros((1, 3, 3)),
                                faces=np.array([3]), skipped=np.array([skipped]), recovered=np.array([1]),
                                names=np.array(["неизвестно"]), groups=np.array([0]),
                                instance_groups=np.array([0]), instances=np.array([0]))
            report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
            return DummyProcess()
        return run

    monkeypatch.setattr(cad_transport.subprocess, "Popen", spawn(2))
    result = CadJob().run(tmp_path / "fixture.step", 2)
    assert result.face_count == 3 and result.skipped_faces == 2 and result.recovered_faces == 1
    monkeypatch.setattr(cad_transport.subprocess, "Popen", spawn(3))
    with pytest.raises(CadPreviewError, match="output"):
        CadJob().run(tmp_path / "fixture.step", 2)


def test_recovered_faces_must_fit_total():
    triangles = np.zeros((1, 3, 3))
    assert CadMesh(triangles, 4, 1, 2).recovered_faces == 2
    for recovered in (-1, 4, 5):
        with pytest.raises(ValueError):
            CadMesh(triangles, 4, 1, recovered)


def test_part_isolation_and_group_validation():
    triangles = np.array([[[0., 0, 0], [1, 0, 0], [0, 1, 0]],
                          [[10., 0, 0], [11, 0, 0], [10, 1, 0]]])
    indices = np.array([1, 0], dtype=np.int32)
    mesh = CadMesh(triangles, 2, 0, 1, ("Прочие", "Отбойник"), indices)
    indices[0] = 0
    assert not mesh.triangle_parts.flags.writeable
    assert mesh.isolated(1).triangles == pytest.approx(triangles[:1])
    assert mesh.isolated(0).triangles == pytest.approx(triangles[1:])
    assert mesh.isolated(1).recovered_faces == 1
    with pytest.raises(ValueError):
        mesh.isolated(2)
    for names, groups in [
        (("",), np.array([0, 0])),
        (("x\ny",), np.array([0, 0])),
        (("part",), np.array([0, 1])),
        (("part",), np.array([-1, 0])),
        (("part",), np.array([0.])),
        (("part",), np.array([0., 0.])),
        ((), np.array([0, 0])),
    ]:
        with pytest.raises(ValueError):
            CadMesh(triangles, 2, 0, 0, names, groups)


def test_projection_matches_camera_basis_and_stable_depth_order():
    from math import cos, sin

    from suspensionlab.core.cad_mesh import project_points

    rng = np.random.default_rng(42)
    triangles = rng.normal(size=(30, 3, 3))
    center = np.array([4., -3., 2.])
    for yaw, elevation in ((0., 0.), (0.9, -0.4), (-2., 1.1)):
        sy, cy, se, ce = sin(yaw), cos(yaw), sin(elevation), cos(elevation)
        right = np.array([cy, sy, 0.])
        up = np.array([-sy * se, cy * se, ce])
        points = triangles - center
        expected = np.stack((points @ right, points @ up), axis=-1)
        depth = (points @ np.cross(right, up)).mean(axis=1)
        actual, order = project_points(triangles, center, yaw, elevation)
        assert actual == pytest.approx(expected, abs=1e-12)
        assert np.array_equal(order, np.argsort(depth, kind="stable"))


def test_interaction_simplification_preserves_full_mesh_and_small_group():
    from suspensionlab.core.cad_interaction import interaction_triangles

    grid = np.arange(80)
    x, y = np.meshgrid(grid, grid)
    points = np.stack((x.ravel(), y.ravel(), np.zeros(x.size)), axis=1).astype(float)
    a = np.stack((points, points + (1, 0, 0), points + (0, 1, 0)), axis=1)
    b = np.stack((points + (1, 1, 0), points + (1, 0, 0), points + (0, 1, 0)), axis=1)
    small = np.array([[[200., 0, 0], [201, 0, 0], [200, 1, 0]]])
    original = np.concatenate((a, b, small))
    parts = np.concatenate((np.ones(len(a) + len(b), dtype=int), [2]))
    mesh = CadMesh(original, 1, 0, 0, ("Прочие", "Плоскость", "Мелкая"), parts)
    result = interaction_triangles(mesh)
    assert len(result) < len(original) and len(result) > 1
    assert np.array_equal(result[-1], small[0])
    assert np.array_equal(mesh.triangles, original) and not mesh.triangles.flags.writeable
    assert interaction_triangles(CadMesh(small, 1)) is not None


def test_interaction_keeps_fully_degenerate_group_instead_of_dropping_it():
    from suspensionlab.core.cad_interaction import interaction_triangles

    triangles = np.zeros((12_001, 3, 3))
    triangles[:, :, 0] = np.arange(len(triangles))[:, None] / 100
    mesh = CadMesh(triangles, 1)
    assert np.array_equal(interaction_triangles(mesh), triangles)


def test_raster_draws_nearest_triangle_and_honors_background():
    from suspensionlab.core.cad_raster import rasterize

    triangles = np.array([[[-2, 0, -2], [2, 0, -2], [0, 0, 2]],
                          [[-2, -1, -2], [2, -1, -2], [0, -1, 2]]], dtype=float)
    image = rasterize(triangles, np.array([105, 205], dtype=np.uint8), np.zeros(3), 3,
                      0, 0, 1, 100, 100, (10, 20, 30))
    assert image.getpixel((0, 0)) == (10, 20, 30)
    assert image.getpixel((50, 50)) == (205 * 3 // 4, 205 * 9 // 10, 205)


def test_instance_validation_and_isolation():
    triangles = np.array([[[0., 0, 0], [1, 0, 0], [0, 1, 0]],
                          [[10., 0, 0], [11, 0, 0], [10, 1, 0]],
                          [[20., 0, 0], [21, 0, 0], [20, 1, 0]]])
    groups = np.array([1, 1, 0])
    instances = np.array([1, 2, 0])
    mesh = CadMesh(triangles, 3, 0, 1, ("Прочие", "Деталь"), groups, (0, 1, 1), instances)
    instances[:] = 0
    assert not mesh.triangle_instances.flags.writeable
    assert mesh.isolated_instance(1).triangles == pytest.approx(triangles[:1])
    assert mesh.isolated_instance(2).triangles == pytest.approx(triangles[1:2])
    assert mesh.isolated(1).triangles == pytest.approx(triangles[:2])
    assert mesh.isolated_instance(1).recovered_faces == 1
    for value in (0, 3):
        with pytest.raises(ValueError):
            mesh.isolated_instance(value)
    for parents, mapping in [
        ((0, 1), np.array([1, 2, 0])),
        ((0, 1, 1), np.array([-1, 2, 0])),
        ((0, 1, 1), np.array([1., 2., 0.])),
        ((0, 1, 1), np.array([1, 2])),
        ((1, 1, 1), np.array([1, 2, 0])),
        ((0, 1, 2), np.array([1, 2, 0])),
        ((0, 1, 0), np.array([1, 2, 0])),
        ((0, 1, 1), np.array([1, 2, 1])),  # instance doesn't match group 0
    ]:
        with pytest.raises(ValueError):
            CadMesh(triangles, 3, 0, 0, ("Прочие", "Деталь"), groups, parents, mapping)
    with pytest.raises(ValueError):
        CadMesh(triangles, 3, instance_groups=(0,), triangle_instances=np.array([0, 0, 0]))
    with pytest.raises(ValueError):
        CadMesh(triangles, 3, instance_groups=(0,))


def test_transport_rejects_bad_instance_mapping(monkeypatch, tmp_path):
    import json
    from pathlib import Path

    from suspensionlab.core import cad_transport

    class DummyProcess:
        def wait(self, timeout=None):
            return 0

    def spawn(command, **kwargs):
        output, report = Path(command[-3]), Path(command[-2])
        np.savez_compressed(output, triangles=np.zeros((1, 3, 3)), faces=np.array([1]),
                            skipped=np.array([0]), recovered=np.array([0]),
                            names=np.array(["Прочие", "Деталь"]), groups=np.array([0]),
                            instance_groups=np.array([0, 1]), instances=np.array([1]))
        report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        return DummyProcess()

    monkeypatch.setattr(cad_transport.subprocess, "Popen", spawn)
    with pytest.raises(CadPreviewError, match="output"):
        CadJob().run(tmp_path / "fixture.step", 2)


def test_highlight_obeys_depth_unless_through_is_explicit():
    from suspensionlab.core.cad_raster import COLORS, HIGHLIGHT_COLORS, rasterize

    # При нулевых углах камера направлена вдоль оси Y: y=-1 ближе к наблюдателю.
    triangles = np.array([[[-2, 0, -2], [2, 0, -2], [0, 0, 2]],
                          [[-2, -1, -2], [2, -1, -2], [0, -1, 2]]], dtype=float)
    shades = np.array([105, 205], dtype=np.uint8)
    selected = np.array([True, False])
    args = (triangles, shades, np.zeros(3), 3, 0, 0, 1, 100, 100, (10, 20, 30))
    normal = rasterize(*args, highlight=selected)
    overlay = rasterize(*args, highlight=selected, through=True)
    front = rasterize(*args, highlight=np.array([False, True]))
    assert normal.getpixel((50, 50)) == COLORS[205]
    assert overlay.getpixel((50, 50)) == HIGHLIGHT_COLORS[105]
    assert front.getpixel((50, 50)) == HIGHLIGHT_COLORS[205]
    assert overlay.getpixel((0, 0)) == (10, 20, 30)
    with pytest.raises(ValueError):
        rasterize(*args, highlight=np.array([1, 0]))
    with pytest.raises(ValueError):
        rasterize(*args, highlight=np.array([True]))


def test_fast_mesh_retains_highlight_separately_from_unselected_triangles():
    from suspensionlab.core.cad_interaction import interaction_geometry

    x, y = np.meshgrid(np.arange(80), np.arange(80))
    p = np.stack((x.ravel(), y.ravel(), np.zeros(x.size)), axis=1).astype(float)
    first = np.stack((p, p + (1, 0, 0), p + (0, 1, 0)), axis=1)
    second = np.stack((p + (1, 1, 0), p + (1, 0, 0), p + (0, 1, 0)), axis=1)
    triangles = np.concatenate((first, second, first[:1]))
    mesh = CadMesh(triangles, 1, part_names=("прочие", "рычаг"), triangle_parts=np.ones(len(triangles), dtype=int))
    highlight = np.zeros(len(triangles), dtype=bool)
    highlight[-1] = True  # Совпадает с другой, невыделенной гранью той же группы.
    fast, fast_highlight = interaction_geometry(mesh, highlight)
    assert len(fast) < len(mesh.triangles) and fast_highlight is not None
    assert fast_highlight.dtype == bool and np.count_nonzero(fast_highlight) == 1
    assert np.array_equal(fast[fast_highlight], triangles[-1:])
    assert np.any(~fast_highlight) and np.array_equal(mesh.triangles, triangles)
    with pytest.raises(ValueError):
        interaction_geometry(mesh, np.ones(len(triangles), dtype=np.int32))
