"""Численные проверки визуальной сетки, не инженерной точности CAD."""
from threading import Event

import numpy as np
import pytest

from suspensionlab.core.cad_mesh import MAX_COORDINATE, CadMesh, project_triangles
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


def test_pick_matches_drawn_pixel_and_explicit_through_overlay():
    from suspensionlab.core.cad_raster import pick_triangle

    triangles = np.array([[[-2, 0, -2], [2, 0, -2], [0, 0, 2]],
                          [[-2, -1, -2], [2, -1, -2], [0, -1, 2]]], dtype=float)
    args = (triangles, np.zeros(3), 3, 0, 0, 1, 100, 100)
    assert pick_triangle(*args, 50, 50) == 1
    assert pick_triangle(*args, 50, 50, highlight=np.array([True, False]), through=True) == 0
    assert pick_triangle(*args, 0, 0) is None
    assert pick_triangle(*args, -1, 0) is None
    assert pick_triangle(*args, 100, 50) is None
    with pytest.raises(ValueError):
        pick_triangle(*args, 50, 50, highlight=np.array([1, 0]))


@pytest.mark.parametrize("offset", [(0., 0.), (17.25, -13.5)])
def test_pick_agrees_with_full_image_rasterization_including_triangle_edges(offset):
    from PIL import Image, ImageDraw

    from suspensionlab.core.cad_raster import pick_triangle, screen_projection

    rng = np.random.default_rng(44)
    triangles = rng.uniform(-4, 4, (100, 3, 3))
    # Один вырожденный треугольник рисуется как линия и тоже может быть выбран.
    triangles[0, 2] = triangles[0, 1]
    center = np.zeros(3)
    radius = 6.
    yaw, elevation, zoom = 0.6, -0.3, 1.3
    width, height = 137, 103
    points, order = screen_projection(triangles, center, radius, yaw, elevation, zoom, width, height, offset=offset)
    selected = np.arange(len(triangles)) % 7 == 0
    coordinates = points.reshape(-1, 6).tolist()
    for through in (False, True):
        image = Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        def draw_id(index, draw=draw):
            identifier = int(index) + 1
            draw.polygon(coordinates[index], fill=(0, (identifier >> 8) & 255, identifier & 255))
        for index in order:
            draw_id(index)
        if through:
            for index in order[selected[order]]:
                draw_id(index)
        samples = [(int(x), int(y)) for x, y in zip(rng.integers(0, width, 300), rng.integers(0, height, 300), strict=True)]
        samples += [(int(x), int(y)) for x, y in points.reshape(-1, 2) if 0 <= x < width and 0 <= y < height]
        for x, y in samples:
            r, g, b = image.getpixel((x, y))
            identifier = (r << 16) | (g << 8) | b
            actual = pick_triangle(triangles, center, radius, yaw, elevation, zoom, width, height, x, y,
                                   highlight=selected, through=through, offset=offset)
            assert actual == (identifier - 1 if identifier else None), (x, y, through)


def test_panning_keeps_raster_picking_and_measurement_in_same_frame():
    from suspensionlab.core.cad_measurement import point_on_projected_triangle
    from suspensionlab.core.cad_raster import COLORS, pick_triangle, rasterize, screen_projection

    triangle = np.array([[[-2., 0, -2], [2, 0, -2], [0, 0, 2]]])
    center = np.zeros(3)
    base = (triangle, center, 3., 0., 0., 1., 100, 100)
    offset = (23., -17.)
    before, _ = screen_projection(*base)
    after, _ = screen_projection(*base, offset=offset)
    assert after - before == pytest.approx(np.broadcast_to(offset, after.shape))
    x, y = 50 + int(offset[0]), 50 + int(offset[1])
    image = rasterize(triangle, np.array([150], dtype=np.uint8), center, 3., 0., 0., 1., 100, 100,
                      (255, 255, 255), offset=offset)
    assert image.getpixel((x, y)) == COLORS[150]
    assert pick_triangle(*base, x, y, offset=offset) == 0
    assert point_on_projected_triangle(triangle[0], after[0], x, y) == pytest.approx((0., 0., 0.))
    assert pick_triangle(*base, 50, 50, offset=offset) is None


def test_orbit_projection_is_continuous_at_poles_and_periodic():
    from math import pi

    from suspensionlab.core.cad_mesh import project_points

    triangles = np.array([[[2., 3., 5.], [-4., 6., 1.], [3., -2., 7.]]])
    center = np.zeros(3)
    for yaw in (-1.1, 0., 1.4):
        for pole in (-pi / 2, pi / 2):
            before, _ = project_points(triangles, center, yaw, pole - 1e-7)
            after, _ = project_points(triangles, center, yaw, pole + 1e-7)
            assert before == pytest.approx(after, abs=2e-6)
        ref, _ = project_points(triangles, center, yaw, 0.4)
        full, _ = project_points(triangles, center, yaw + 2 * pi, 0.4 + 2 * pi)
        assert full == pytest.approx(ref, abs=1e-12)


def test_mesh_above_old_limit_is_accepted():
    triangles = np.zeros((125_000, 3, 3))
    mesh = CadMesh(triangles, 125_000)
    assert len(mesh.triangles) == 125_000 and mesh.face_count == 125_000


def test_uncompressed_large_transport_above_old_32_mib_limit(monkeypatch, tmp_path):
    import json
    from pathlib import Path

    from suspensionlab.core import cad_transport
    class Process:
        def wait(self, timeout=None):
            return 0
    def spawn(command, **kwargs):
        output, report = Path(command[-3]), Path(command[-2])
        triangles = np.zeros((500_000, 3, 3))
        np.savez(output, triangles=triangles, faces=np.array([1]), skipped=np.array([0]),
                 recovered=np.array([0]), names=np.array(["part"]), groups=np.zeros(500_000, dtype=np.int32),
                 instance_groups=np.array([0]), instances=np.zeros(500_000, dtype=np.int32))
        assert output.stat().st_size > 32 * 1024 * 1024
        report.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        return Process()
    monkeypatch.setattr(cad_transport.subprocess, "Popen", spawn)
    mesh = CadJob().run(tmp_path / "large.step", 2)
    assert len(mesh.triangles) == 500_000


def test_progress_reports_only_known_stages(monkeypatch, tmp_path):
    import json
    import subprocess
    from pathlib import Path

    from suspensionlab.core import cad_transport
    class Process:
        def __init__(self, command, env):
            self.output, self.report = Path(command[-3]), Path(command[-2])
            self.progress = Path(env["SUSPENSIONLAB_CAD_PROGRESS_PATH"])
            self.calls = 0
        def wait(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                self.progress.write_text(json.dumps({"stage": "faces", "faces": 200}))
                raise subprocess.TimeoutExpired("worker", timeout)
            np.savez(self.output, triangles=np.zeros((1, 3, 3)), faces=np.array([1]), skipped=np.array([0]),
                     recovered=np.array([0]), names=np.array(["part"]), groups=np.array([0]),
                     instance_groups=np.array([0]), instances=np.array([0]))
            self.report.write_text(json.dumps({"status": "ok"}))
            return 0
    monkeypatch.setattr(cad_transport.subprocess, "Popen", lambda command, **kw: Process(command, kw["env"]))
    job = CadJob()
    progress = []
    job.progress_callback = lambda stage, faces: progress.append((stage, faces))
    job.run(tmp_path / "model.step", 2)
    assert progress == [("faces", 200)]


def test_mesh_memory_budget_is_checked_before_copy(monkeypatch):
    from suspensionlab.core import cad_mesh
    monkeypatch.setattr(cad_mesh, "MAX_MESH_BYTES", 72)
    CadMesh(np.zeros((1, 3, 3)), 1)
    with pytest.raises(ValueError, match="сетка|Сетка"):
        CadMesh(np.zeros((2, 3, 3)), 1)


def test_chunked_raster_matches_simple_reference():
    from PIL import Image, ImageDraw

    from suspensionlab.core.cad_raster import COLORS, HIGHLIGHT_COLORS, rasterize, screen_projection
    rng = np.random.default_rng(123)
    triangles = rng.uniform(-1, 1, (5000, 3, 3))
    shades = rng.integers(105, 206, 5000, dtype=np.uint8)
    highlight = rng.random(5000) < .1
    args = (triangles, shades, np.zeros(3), 2., 0.3, -0.1, 1., 90, 100, (20, 30, 40))
    for through in (False, True):
        projected, order = screen_projection(triangles, np.zeros(3), 2., .3, -.1, 1., 90, 100)
        image = Image.new("RGB", (90, 100), (20, 30, 40))
        draw = ImageDraw.Draw(image)
        for index in order:
            color = (HIGHLIGHT_COLORS if highlight[index] else COLORS)[shades[index]]
            draw.polygon(projected[index].reshape(6).tolist(), fill=color)
        if through:
            for index in order[highlight[order]]:
                draw.polygon(projected[index].reshape(6).tolist(), fill=HIGHLIGHT_COLORS[shades[index]])
        assert np.array_equal(np.asarray(rasterize(*args, highlight=highlight, through=through)), np.asarray(image))


def test_large_interaction_is_bounded_and_preserves_highlight():
    from suspensionlab.core.cad_interaction import interaction_geometry
    rng = np.random.default_rng(22)
    triangles = rng.uniform(-1, 1, (201_000, 3, 3))
    mesh = CadMesh(triangles, 1)
    mask = np.zeros(len(triangles), dtype=bool)
    mask[-1000:] = True
    fast, selected = interaction_geometry(mesh, mask)
    assert len(fast) < len(triangles) and selected is not None
    assert selected.any() and (~selected).any()
