"""Real-context test: opt in with SUSPENSIONLAB_TEST_OPENGL=1 and a working display.

This may use Mesa software OpenGL in CI; it does not establish hardware support.
"""
import os

import numpy as np
import pytest

from suspensionlab.core.cad_mesh import CadMesh
from suspensionlab.core.cad_raster import COLORS, HIGHLIGHT_COLORS
from suspensionlab.ui.canvas.cad_gl_renderer import CadGlRenderer

pytestmark = pytest.mark.skipif(os.environ.get("SUSPENSIONLAB_TEST_OPENGL") != "1",
                                reason="requires an explicitly enabled real OpenGL context")


def test_real_context_frame_and_visible_triangle(qtbot):
    triangles = np.array([[[-1, 0, -1], [1, 0, -1], [0, 0, 1]],
                          [[-1, 2, -1], [1, 2, -1], [0, 2, 1]]], dtype=float)
    mesh = CadMesh(triangles, 2)
    center, radius = mesh.bounds()
    shades = np.array([150, 160], dtype=np.uint8)
    highlight = np.array([False, True])
    renderer = CadGlRenderer(allow_software=True)
    try:
        assert renderer.vendor and renderer.renderer and renderer.version
        renderer.set_mesh(mesh, center, radius, shades, highlight)
        args = (center, 0., 0., 1., 320, 280, 24., (0., 0.), highlight)
        image = renderer.render(*args, False, (255, 255, 255))
        assert not image.isNull()
        pixel = image.pixelColor(160, 140)
        assert (pixel.red(), pixel.green(), pixel.blue()) == COLORS[150]
        assert renderer.pick(*args, False, 160, 140) == 0
        assert renderer.pick(*args, False, 0, 0) is None
        image = renderer.render(*args, True, (255, 255, 255))
        pixel = image.pixelColor(160, 140)
        assert (pixel.red(), pixel.green(), pixel.blue()) == HIGHLIGHT_COLORS[160]
        assert renderer.pick(*args, True, 160, 140) == 1
    finally:
        renderer.close()
