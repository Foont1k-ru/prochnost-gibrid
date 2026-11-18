"""Оси стандартных видов без предположений о произвольном STEP."""
import numpy as np
import pytest

from suspensionlab.core.cad_mesh import project_points
from suspensionlab.core.camera_views import CAMERA_VIEWS, camera_view_angles
from suspensionlab.core.scene3d import project_orthographic


@pytest.mark.parametrize(("name", "screen_right", "screen_up", "camera_side"), [
    ("front", (0, 1, 0), (0, 0, 1), (1, 0, 0)),
    ("rear", (0, -1, 0), (0, 0, 1), (-1, 0, 0)),
    ("left", (-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    ("right", (1, 0, 0), (0, 0, 1), (0, -1, 0)),
    ("top", (1, 0, 0), (0, 1, 0), (0, 0, 1)),
    ("bottom", (1, 0, 0), (0, -1, 0), (0, 0, -1)),
])
def test_axes_and_depth_match_scalar_and_cad_projections(name, screen_right, screen_up, camera_side):
    yaw, elevation = camera_view_angles(name)
    assert project_orthographic(screen_right, (0, 0, 0), yaw, elevation) == pytest.approx((1, 0), abs=1e-12)
    assert project_orthographic(screen_up, (0, 0, 0), yaw, elevation) == pytest.approx((0, 1), abs=1e-12)
    assert project_orthographic(camera_side, (0, 0, 0), yaw, elevation) == pytest.approx((0, 0), abs=1e-12)
    sides = np.array([-np.array(camera_side), np.zeros(3), np.array(camera_side)])
    triangles = np.repeat(sides[:, None, :], 3, axis=1)
    screen, order = project_points(triangles, np.zeros(3), yaw, elevation)
    assert screen == pytest.approx(np.zeros((3, 3, 2)), abs=1e-12)
    assert tuple(order) == (0, 1, 2)


def test_default_and_unknown_direction():
    assert camera_view_angles("default") == (-0.65, 0.35)
    assert len(CAMERA_VIEWS) == 7
    with pytest.raises(ValueError, match="направление"):
        camera_view_angles("unknown")


@pytest.mark.parametrize(("name", "right", "up"), [
    ("front", (0, 1, 0), (0, 0, 1)),
    ("rear", (0, -1, 0), (0, 0, 1)),
    ("left", (-1, 0, 0), (0, 0, 1)),
    ("right", (1, 0, 0), (0, 0, 1)),
    ("top", (1, 0, 0), (0, 1, 0)),
    ("bottom", (1, 0, 0), (0, -1, 0)),
])
def test_cad_picking_and_measurement_after_standard_view(qtbot, name, right, up):
    from PySide6.QtCore import QPoint, Qt

    from suspensionlab.core.cad_mesh import CadMesh
    from suspensionlab.ui.canvas.cad_preview import CadPreview

    right, up = np.array(right, dtype=float), np.array(up, dtype=float)
    tri = np.array([[-10 * right - 10 * up, 10 * right - 10 * up, 10 * up]])
    view = CadPreview()
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    view.set_mesh(CadMesh(tri, 1, part_names=("Деталь",), triangle_parts=np.array([0])))
    view.pan_x, view.pan_y, view.zoom = 20., -10., 1.25
    view.set_standard_view(name)
    assert not view.grab().isNull()
    chosen = []
    view.triangle_picked.connect(chosen.append)
    pos = QPoint(view.width() // 2 + 20, view.height() // 2 - 10)
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=pos)
    assert chosen == [0]
    measured = []
    view.point_picked.connect(measured.append)
    view.set_measure_mode(True)
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=pos)
    assert len(measured) == 1 and np.linalg.norm(measured[0]) < 0.3
    view.set_markers((measured[0],))
    view.set_standard_view("default")
    assert view._markers == (measured[0],) and np.array_equal(view.mesh.triangles, tri)
    current = (view.yaw, view.elevation, view.pan_x, view.pan_y, view.zoom)
    with pytest.raises(ValueError):
        view.set_standard_view("not-a-view")
    assert (view.yaw, view.elevation, view.pan_x, view.pan_y, view.zoom) == current
