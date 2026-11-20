"""Experimental off-screen OpenGL CAD renderer; no CAD calculations are performed here."""
from __future__ import annotations

import ctypes
from math import cos, sin

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

from ...core.cad_gpu_projection import clip_matrix, normalized_vertices
from ...core.cad_mesh import CadMesh
from ...core.cad_raster import COLORS, HIGHLIGHT_COLORS

# The CPU mesh, normalized vertices, vertex colours, indices, GL buffers and
# framebuffer coexist. Do not attempt unbounded allocations in a GUI process.
MAX_GL_TRIANGLES = 1_000_000
MAX_GL_PIXELS = 8_000_000

_VERTEX = """
attribute vec3 position;
attribute vec3 colour;
uniform mat4 camera;
varying vec3 vcolour;
void main() { gl_Position = camera * vec4(position, 1.0); vcolour = colour; }
"""
_FRAGMENT = """
#ifdef GL_ES
precision highp float;
#endif
varying vec3 vcolour;
void main() { gl_FragColor = vec4(vcolour, 1.0); }
"""


def software_renderer(renderer: str) -> bool:
    """Recognise known software renderers; False does not prove hardware use."""
    text = renderer.lower()
    return any(name in text for name in ("llvmpipe", "softpipe", "swrast", "swiftshader",
                                          "software rasterizer", "microsoft basic render", "gdi generic"))


def triangle_order(triangles: np.ndarray, center: np.ndarray, yaw: float, elevation: float) -> np.ndarray:
    """Match the CPU painter's stable average-depth order without projecting all vertices."""
    points = triangles - center
    sy, cy, se, ce = sin(yaw), cos(yaw), sin(elevation), cos(elevation)
    x, y, z = points[:, :, 0], points[:, :, 1], points[:, :, 2]
    return np.argsort((sy * ce * x - cy * ce * y + se * z).mean(axis=1), kind="stable")


class CadGlRenderer:
    """A separate off-screen context makes failure and fallback independent of QWidget painting."""

    def __init__(self, *, allow_software: bool = False) -> None:
        # allow_software is for real-context tests, not the user-facing mode.
        # Lazy import permits the existing software renderer to run without PyOpenGL.
        from OpenGL import GL
        from OpenGL.GL import shaders

        self.gl = GL
        self.context = QOpenGLContext()
        fmt = QSurfaceFormat()
        fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        fmt.setVersion(2, 0)
        fmt.setSamples(0)
        self.context.setFormat(fmt)
        if not self.context.create() or self.context.isOpenGLES():
            raise RuntimeError("OpenGL context unavailable or unsupported")
        self.surface = QOffscreenSurface()
        self.surface.setFormat(self.context.format())
        self.surface.create()
        if not self.surface.isValid() or not self.context.makeCurrent(self.surface):
            raise RuntimeError("OpenGL off-screen surface unavailable")
        self.program = 0
        self.buffers: list[int] = []
        self.fbo: QOpenGLFramebufferObject | None = None
        self.mesh: CadMesh | None = None
        self.count = 0
        try:
            self.vendor = self._string(GL.GL_VENDOR)
            self.renderer = self._string(GL.GL_RENDERER)
            self.version = self._string(GL.GL_VERSION)
            if not self.renderer or not self.version:
                raise RuntimeError("OpenGL renderer identity unavailable")
            if software_renderer(self.renderer) and not allow_software:
                raise RuntimeError("Software OpenGL renderer: " + self.renderer)
            self.program = int(shaders.compileProgram(shaders.compileShader(_VERTEX, GL.GL_VERTEX_SHADER),
                                                       shaders.compileShader(_FRAGMENT, GL.GL_FRAGMENT_SHADER)))
            self.position = int(GL.glGetAttribLocation(self.program, "position"))
            self.colour = int(GL.glGetAttribLocation(self.program, "colour"))
            self.camera = int(GL.glGetUniformLocation(self.program, "camera"))
            if min(self.position, self.colour, self.camera) < 0:
                raise RuntimeError("OpenGL shader attributes unavailable")
            self.buffers = [int(v) for v in GL.glGenBuffers(4)]
            if not all(self.buffers):
                raise RuntimeError("OpenGL buffer allocation failed")
        except Exception:
            self.close()
            raise
        finally:
            self.context.doneCurrent()

    def _string(self, name: int) -> str:
        value = self.gl.glGetString(name)
        return value.decode("utf-8", "replace") if value else ""

    def _current(self) -> None:
        if not self.context.isValid() or not self.context.makeCurrent(self.surface):
            raise RuntimeError("OpenGL context lost")

    def close(self) -> None:
        try:
            if self.context.isValid() and self.context.makeCurrent(self.surface):
                self.fbo = None
                if self.buffers:
                    self.gl.glDeleteBuffers(len(self.buffers), self.buffers)
                    self.buffers = []
                if self.program:
                    self.gl.glDeleteProgram(self.program)
                    self.program = 0
                self.context.doneCurrent()
        except Exception:
            # Context loss can make GL deletion impossible; Qt will release it.
            pass
        self.surface.destroy()

    def set_mesh(self, mesh: CadMesh, center: np.ndarray, radius: float, shades: np.ndarray,
                 highlight: np.ndarray | None) -> None:
        if len(mesh.triangles) > MAX_GL_TRIANGLES:
            raise RuntimeError("OpenGL mesh budget exceeded")
        gl = self.gl
        vertices = normalized_vertices(mesh.triangles, center, radius)
        colours = np.asarray(COLORS, dtype=np.uint8)[shades]
        if highlight is not None:
            colours[highlight] = np.asarray(HIGHLIGHT_COLORS, dtype=np.uint8)[shades[highlight]]
        colours = np.repeat(colours, 3, axis=0)
        ids = np.arange(1, len(mesh.triangles) + 1, dtype=np.uint32)
        ids = np.stack(((ids >> 16) & 255, (ids >> 8) & 255, ids & 255), axis=1).astype(np.uint8)
        ids = np.repeat(ids, 3, axis=0)
        self._current()
        try:
            for handle, data in zip(self.buffers[:3], (vertices, colours, ids), strict=True):
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, handle)
                gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data, gl.GL_STATIC_DRAW)
            self.mesh = mesh
            self.count = len(mesh.triangles)
        finally:
            self.context.doneCurrent()

    def _draw(self, center: np.ndarray, yaw: float, elevation: float, zoom: float, width: int, height: int,
              margin: float, offset: tuple[float, float], highlight: np.ndarray | None, through: bool,
              background: tuple[int, int, int], picking: bool) -> None:
        if self.mesh is None or width <= 0 or height <= 0 or width * height > MAX_GL_PIXELS:
            raise RuntimeError("OpenGL framebuffer budget exceeded or mesh unavailable")
        gl = self.gl
        if self.fbo is None or self.fbo.width() != width or self.fbo.height() != height:
            self.fbo = None
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setSamples(0)
            fmt.setInternalTextureFormat(gl.GL_RGBA8)
            self.fbo = QOpenGLFramebufferObject(width, height, fmt)
        if not self.fbo.isValid() or not self.fbo.bind():
            raise RuntimeError("OpenGL framebuffer unavailable")
        order = triangle_order(self.mesh.triangles, center, yaw, elevation)
        if through and highlight is not None:
            order = np.concatenate((order, order[highlight[order]]))
        indices = (order[:, None] * 3 + np.arange(3)).astype(np.uint32).reshape(-1)
        gl.glViewport(0, 0, width, height)
        for option in (gl.GL_BLEND, gl.GL_DEPTH_TEST, gl.GL_CULL_FACE, gl.GL_DITHER, gl.GL_SCISSOR_TEST):
            gl.glDisable(option)
        gl.glClearColor(*(tuple(v / 255 for v in background) if not picking else (0., 0., 0.)), 1.)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glUseProgram(self.program)
        matrix = np.ascontiguousarray(clip_matrix(yaw, elevation, zoom, width, height, margin, offset).T,
                                      dtype=np.float32)
        gl.glUniformMatrix4fv(self.camera, 1, gl.GL_FALSE, matrix)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.buffers[0])
        gl.glEnableVertexAttribArray(self.position)
        gl.glVertexAttribPointer(self.position, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.buffers[2 if picking else 1])
        gl.glEnableVertexAttribArray(self.colour)
        gl.glVertexAttribPointer(self.colour, 3, gl.GL_UNSIGNED_BYTE, gl.GL_TRUE, 0, ctypes.c_void_p(0))
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.buffers[3])
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, gl.GL_STREAM_DRAW)
        gl.glDrawElements(gl.GL_TRIANGLES, len(indices), gl.GL_UNSIGNED_INT, ctypes.c_void_p(0))
        gl.glDisableVertexAttribArray(self.position)
        gl.glDisableVertexAttribArray(self.colour)
        gl.glUseProgram(0)

    def render(self, center: np.ndarray, yaw: float, elevation: float, zoom: float, width: int, height: int,
               margin: float, offset: tuple[float, float], highlight: np.ndarray | None, through: bool,
               background: tuple[int, int, int]) -> QImage:
        self._current()
        try:
            self._draw(center, yaw, elevation, zoom, width, height, margin, offset, highlight, through,
                       background, False)
            data = bytes(self.gl.glReadPixels(0, 0, width, height, self.gl.GL_RGBA, self.gl.GL_UNSIGNED_BYTE))
            if len(data) != width * height * 4:
                raise RuntimeError("OpenGL frame readback has an unexpected size")
            image = QImage(data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy().flipped(
                Qt.Orientation.Vertical
            )
            if image.isNull():
                raise RuntimeError("OpenGL frame readback failed")
            return image
        finally:
            if self.fbo:
                self.fbo.release()
            self.context.doneCurrent()

    def pick(self, center: np.ndarray, yaw: float, elevation: float, zoom: float, width: int, height: int,
             margin: float, offset: tuple[float, float], highlight: np.ndarray | None, through: bool,
             x: int, y: int) -> int | None:
        if not (0 <= x < width and 0 <= y < height):
            return None
        self._current()
        try:
            self._draw(center, yaw, elevation, zoom, width, height, margin, offset, highlight, through,
                       (0, 0, 0), True)
            data = bytes(self.gl.glReadPixels(x, height - 1 - y, 1, 1, self.gl.GL_RGBA, self.gl.GL_UNSIGNED_BYTE))
            if len(data) != 4:
                raise RuntimeError("OpenGL pick readback has an unexpected size")
            red, green, blue = data[:3]
            value = (red << 16) | (green << 8) | blue
            return value - 1 if 0 < value <= self.count else None
        finally:
            if self.fbo:
                self.fbo.release()
            self.context.doneCurrent()
