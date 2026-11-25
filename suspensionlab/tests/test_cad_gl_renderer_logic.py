"""Exercise GL command/data plumbing with fakes, not a real driver."""
import numpy as np
import pytest

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_raster import COLORS, HIGHLIGHT_COLORS
from suspensionlab.ui.canvas import cad_gl_renderer
from suspensionlab.ui.canvas.cad_gl_renderer import CadGlRenderer


class FakeContext:
    def isValid(self):  # noqa: N802
        return True

    def makeCurrent(self, surface):  # noqa: N802
        return True

    def doneCurrent(self):  # noqa: N802
        pass


class FakeFbo:
    def __init__(self, width, height, fmt):
        self.w, self.h = width, height

    def width(self):
        return self.w

    def height(self):
        return self.h

    def isValid(self):  # noqa: N802
        return True

    def bind(self):
        return True

    def release(self):
        pass


class FakeGl:
    GL_ARRAY_BUFFER = 1
    GL_ELEMENT_ARRAY_BUFFER = 2
    GL_STATIC_DRAW = 3
    GL_STREAM_DRAW = 4
    GL_RGBA8 = 5
    GL_BLEND = 6
    GL_DEPTH_TEST = 7
    GL_CULL_FACE = 8
    GL_DITHER = 9
    GL_SCISSOR_TEST = 10
    GL_COLOR_BUFFER_BIT = 11
    GL_FLOAT = 12
    GL_FALSE = 0
    GL_TRUE = 1
    GL_UNSIGNED_BYTE = 13
    GL_TRIANGLES = 14
    GL_UNSIGNED_INT = 15
    GL_RGBA = 16

    def __init__(self):
        self.bound = {}
        self.uploads = {}
        self.reads = []
        self.pixels = b""
        self.draw_count = None

    def glBindBuffer(self, target, buffer):  # noqa: N802
        self.bound[target] = buffer

    def glBufferData(self, target, size, data, usage):  # noqa: N802
        assert size == data.nbytes
        self.uploads[self.bound[target]] = data.copy()

    def glDrawElements(self, mode, count, kind, pointer):  # noqa: N802
        self.draw_count = count

    def glReadPixels(self, *args):  # noqa: N802
        self.reads.append(args)
        return self.pixels

    def __getattr__(self, name):
        if name.startswith("gl"):
            return lambda *args: None
        raise AttributeError(name)


@pytest.fixture
def gl_renderer(monkeypatch):
    monkeypatch.setattr(cad_gl_renderer, "QOpenGLFramebufferObject", FakeFbo)
    renderer = object.__new__(CadGlRenderer)
    renderer.gl = FakeGl()
    renderer.context = FakeContext()
    renderer.surface = None
    renderer.buffers = [101, 102, 103, 104]
    renderer.position, renderer.colour, renderer.camera, renderer.program = 0, 1, 2, 1
    renderer.fbo = None
    renderer.mesh = None
    renderer.count = 0
    return renderer


def test_buffers_draw_order_frame_flip_and_id_readback(gl_renderer):
    renderer = gl_renderer
    triangles = np.array([[[-1, 0, -1], [1, 0, -1], [0, 0, 1]],
                          [[-1, 2, -1], [1, 2, -1], [0, 2, 1]]], dtype=float)
    mesh = CadMesh(triangles, 2)
    center, radius = mesh.bounds()
    shades = np.array([150, 160], dtype=np.uint8)
    highlight = np.array([False, True])
    renderer.set_mesh(mesh, center, radius, shades, highlight)
    colours = renderer.gl.uploads[102]
    np.testing.assert_array_equal(colours[0], COLORS[150])
    np.testing.assert_array_equal(colours[3], HIGHLIGHT_COLORS[160])
    np.testing.assert_array_equal(renderer.gl.uploads[103][0], [0, 0, 1])
    np.testing.assert_array_equal(renderer.gl.uploads[103][3], [0, 0, 2])
    # OpenGL rows are bottom-to-top; Qt image must display top-to-bottom.
    renderer.gl.pixels = bytes([255, 0, 0, 255, 0, 255, 0, 255,
                                0, 0, 255, 255, 255, 255, 0, 255])
    args = (center, 0., 0., 1., 2, 2, 0., (0., 0.), highlight)
    image = renderer.render(*args, True, (0, 0, 0))
    assert image.pixelColor(0, 0).blue() == 255
    assert image.pixelColor(0, 1).red() == 255
    # Second triangle is further; through draws its highlight a second time.
    np.testing.assert_array_equal(renderer.gl.uploads[104], [3, 4, 5, 0, 1, 2, 3, 4, 5])
    assert renderer.gl.draw_count == 9
    renderer.gl.pixels = bytes([0, 0, 2, 255])
    assert renderer.pick(*args, True, 1, 0) == 1
    assert renderer.gl.reads[-1][:4] == (1, 1, 1, 1)
    renderer.gl.pixels = bytes([0, 0, 0, 255])
    assert renderer.pick(*args, True, 0, 1) is None
    renderer.gl.pixels = b"bad"
    with pytest.raises(RuntimeError, match="readback"):
        renderer.pick(*args, True, 0, 1)


def test_frame_budget_rejected_before_allocation(gl_renderer):
    gl_renderer.mesh = CadMesh(np.zeros((1, 3, 3)), 1)
    with pytest.raises(RuntimeError, match="budget"):
        gl_renderer._draw(np.zeros(3), 0., 0., 1., 5000, 5000, 24., (0., 0.), None, False,
                          (0, 0, 0), False)
