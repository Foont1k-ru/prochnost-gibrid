"""Fallback and interaction contract, without pretending a mock is a real GPU."""
import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage

from suspensionlab.core.cad_mesh import CadMesh, project_points
from suspensionlab.ui.canvas import cad_gl_renderer
from suspensionlab.ui.canvas.cad_preview import CadPreview


def mesh():
    triangles = np.array([[[-1, 0, -1], [1, 0, -1], [0, 0, 1]],
                          [[-1, 2, -1], [1, 2, -1], [0, 2, 1]]], dtype=float)
    return CadMesh(triangles, 2, part_names=("first", "second"), triangle_parts=np.array([0, 1]))


class FakeRenderer:
    vendor = "test vendor"
    renderer = "test renderer"
    version = "test version"

    def __init__(self):
        self.closed = False
        self.meshes = []
        self.picks = []

    def set_mesh(self, *args):
        self.meshes.append(args)

    def render(self, center, yaw, elevation, zoom, width, height, margin, offset, highlight, through, background):
        image = QImage(width, height, QImage.Format.Format_RGBA8888)
        image.fill(QColor(10, 20, 30))
        return image

    def pick(self, *args):
        self.picks.append(args)
        return 1

    def close(self):
        self.closed = True


def test_order_agrees_with_existing_cpu_projection():
    data = np.random.default_rng(77).normal(size=(205, 3, 3))
    data[5] = data[2]  # stable ties remain stable
    center = np.array([5., -10., 20.])
    for yaw, elevation in ((0, 0), (0.5, -1.2), (3.1, 1.57)):
        _, expected = project_points(data, center, yaw, elevation)
        np.testing.assert_array_equal(cad_gl_renderer.triangle_order(data, center, yaw, elevation), expected)


def test_software_renderer_is_not_mistaken_for_gpu():
    for name in ("llvmpipe (LLVM 15)", "SwiftShader", "Microsoft Basic Render Driver", "GDI Generic", "softpipe"):
        assert cad_gl_renderer.software_renderer(name)
    assert not cad_gl_renderer.software_renderer("NVIDIA GeForce")
    assert not cad_gl_renderer.software_renderer("unknown")  # not a proof of hardware either


def test_opt_in_uses_gpu_id_and_preserves_camera_and_highlights(qtbot, monkeypatch):
    created = []
    def factory():
        gpu = FakeRenderer()
        created.append(gpu)
        return gpu
    monkeypatch.setattr(cad_gl_renderer, "CadGlRenderer", factory)
    view = CadPreview()
    qtbot.addWidget(view)
    view.set_mesh(mesh())
    view.yaw, view.elevation, view.zoom = 0., 0., 1.2
    view.pan_x, view.pan_y = 3., 4.
    view.show()
    qtbot.waitExposed(view)
    assert not view._renderer_button.isChecked() and not created
    view._renderer_button.click()
    qtbot.waitUntil(lambda: bool(created) and view._frame is not None)
    gpu = created[0]
    assert "test renderer" in view._renderer_button.toolTip()
    assert (view.yaw, view.elevation, view.zoom, view.pan_x, view.pan_y) == (0., 0., 1.2, 3., 4.)
    with qtbot.waitSignal(view.triangle_picked, timeout=1000) as picked:
        qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(view.width() // 2, view.height() // 2))
    assert picked.args == [1] and gpu.picks
    view.set_mesh(view.mesh, np.array([True, False]), through=True)
    qtbot.waitUntil(lambda: len(gpu.meshes) == 2)
    assert gpu.meshes[-1][-1].tolist() == [True, False]
    view._renderer_button.click()
    assert gpu.closed and not view._renderer_button.isChecked()
    assert view.mesh is not None and view.yaw == 0 and view.zoom == 1.2


def test_empty_mesh_releases_gpu_and_new_mesh_can_reinitialize(qtbot, monkeypatch):
    created = []
    def factory():
        gpu = FakeRenderer()
        created.append(gpu)
        return gpu
    monkeypatch.setattr(cad_gl_renderer, "CadGlRenderer", factory)
    view = CadPreview()
    qtbot.addWidget(view)
    view.set_mesh(mesh())
    view.show()
    qtbot.waitExposed(view)
    view._renderer_button.click()
    qtbot.waitUntil(lambda: bool(created) and view._frame is not None)
    view.set_mesh(None)
    assert created[0].closed and view._gpu is None
    assert view._renderer_button.isChecked()
    view.set_mesh(mesh())
    qtbot.waitUntil(lambda: len(created) == 2 and view._frame is not None)
    view.hide()
    assert created[1].closed and view._gpu is None


def test_stale_gpu_frame_does_not_select(qtbot, monkeypatch):
    monkeypatch.setattr(cad_gl_renderer, "CadGlRenderer", FakeRenderer)
    view = CadPreview()
    qtbot.addWidget(view)
    view.set_mesh(mesh())
    view.show()
    qtbot.waitExposed(view)
    view._renderer_button.click()
    qtbot.waitUntil(lambda: view._gpu is not None and view._frame is not None)
    gpu = view._gpu
    picked = []
    view.triangle_picked.connect(picked.append)
    view.yaw += 0.2  # The visible frame is intentionally still from the old camera.
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(view.width() // 2, view.height() // 2))
    assert not picked and not gpu.picks


def test_failed_initialization_falls_back_without_losing_mesh(qtbot, monkeypatch):
    def factory():
        raise RuntimeError("no test context")
    monkeypatch.setattr(cad_gl_renderer, "CadGlRenderer", factory)
    view = CadPreview()
    qtbot.addWidget(view)
    view.set_mesh(mesh())
    view.show()
    qtbot.waitExposed(view)
    view._renderer_button.click()
    qtbot.waitUntil(lambda: not view._renderer_button.isChecked())
    assert view.mesh is not None and view._frame is not None
    assert "no test context" in view._renderer_button.toolTip()


def test_real_renderer_attempt_either_displays_or_falls_back(qtbot):
    # This exercises Qt/context creation, but is not a substitute for a real GL frame test.
    view = CadPreview()
    qtbot.addWidget(view)
    view.set_mesh(mesh())
    view.show()
    qtbot.waitExposed(view)
    view._renderer_button.click()
    qtbot.waitUntil(lambda: view._frame is not None)
    assert view.mesh is not None
    if view._renderer_button.isChecked():
        assert view._gpu is not None and view._gpu.renderer
    else:
        assert view._gpu is None and view._renderer_button.toolTip()


def test_failed_gpu_pick_does_not_pick_cpu_surface(qtbot, monkeypatch):
    class FailingPick(FakeRenderer):
        def pick(self, *args):
            raise RuntimeError("lost context")
    monkeypatch.setattr(cad_gl_renderer, "CadGlRenderer", FailingPick)
    view = CadPreview()
    qtbot.addWidget(view)
    view.set_mesh(mesh())
    view.show()
    qtbot.waitExposed(view)
    view._renderer_button.click()
    qtbot.waitUntil(lambda: view._gpu is not None and view._frame is not None)
    picked = []
    view.triangle_picked.connect(picked.append)
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(view.width() // 2, view.height() // 2))
    assert not picked and not view._renderer_button.isChecked()
    assert "lost context" in view._renderer_button.toolTip()


def test_highlight_changes_reuse_only_immutable_geometry_calculations(qtbot, monkeypatch):
    from suspensionlab.ui.canvas import cad_preview

    counts = {'bounds': 0, 'shades': 0, 'interaction': 0}
    original_bounds = CadMesh.bounds
    original_shades = cad_preview.triangle_shades
    original_interaction = cad_preview.interaction_geometry

    def bounds(current):
        counts['bounds'] += 1
        return original_bounds(current)

    def shades(triangles):
        counts['shades'] += 1
        return original_shades(triangles)

    def interaction(current, highlight):
        counts['interaction'] += 1
        return original_interaction(current, highlight)

    monkeypatch.setattr(CadMesh, 'bounds', bounds)
    monkeypatch.setattr(cad_preview, 'triangle_shades', shades)
    monkeypatch.setattr(cad_preview, 'interaction_geometry', interaction)
    view = CadPreview()
    qtbot.addWidget(view)
    first, second = mesh(), mesh()
    view.set_mesh(first)
    old_shades = view._shades
    revision = view._mesh_revision
    view.set_mesh(first, np.array([True, False]), through=True)
    assert view._shades is old_shades
    assert counts == {'bounds': 1, 'shades': 1, 'interaction': 2}
    assert view._mesh_revision == revision + 1
    assert view._fast_highlight.tolist() == [True, False] and view._through
    view.set_mesh(first, np.array([False, True]))
    assert counts == {'bounds': 1, 'shades': 1, 'interaction': 3}
    assert view._fast_highlight.tolist() == [False, True] and not view._through
    view.set_mesh(second)
    assert counts == {'bounds': 2, 'shades': 2, 'interaction': 4}
    view.set_mesh(None)
    view.set_mesh(first)
    assert counts == {'bounds': 3, 'shades': 3, 'interaction': 5}
