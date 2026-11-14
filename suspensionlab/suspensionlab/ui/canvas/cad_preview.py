"""Ортографический просмотр CAD без OpenGL; быстрый вид при движении камеры."""
from __future__ import annotations

from math import pi, remainder

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

from ...core.cad_interaction import interaction_triangles
from ...core.cad_mesh import CadMesh
from ...core.cad_raster import rasterize, triangle_shades
from ...i18n import tr


class CadPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 280)
        self.mesh: CadMesh | None = None
        self._triangles = np.empty((0, 3, 3))
        self._fast_triangles = self._triangles
        self._shades = np.empty(0, dtype=np.uint8)
        self._fast_shades = self._shades
        self._center = np.zeros(3)
        self._radius = 1.
        self._drag: QPointF | None = None
        self._moving = False
        self._frame_key: tuple | None = None
        self._frame: QImage | None = None
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(200)
        self._settle.timeout.connect(self._finish_moving)
        self.reset_camera()

    def set_mesh(self, mesh: CadMesh | None) -> None:
        self.mesh = mesh
        self._settle.stop()
        self._moving = False
        self._drag = None
        self._frame_key = None
        self._frame = None
        if mesh is None:
            self._triangles = np.empty((0, 3, 3))
            self._fast_triangles = self._triangles
            self._shades = np.empty(0, dtype=np.uint8)
            self._fast_shades = self._shades
        else:
            self._triangles = mesh.triangles
            self._center, self._radius = mesh.bounds()
            self._shades = triangle_shades(self._triangles)
            self._fast_triangles = interaction_triangles(mesh)
            self._fast_shades = (self._shades if self._fast_triangles is self._triangles
                                 else triangle_shades(self._fast_triangles))
        self.update()

    def reset_camera(self) -> None:
        self.yaw, self.elevation, self.zoom = -0.65, 0.35, 1.0
        self._drag = None
        self._settle.stop()
        self._moving = False
        self.update()

    def _finish_moving(self) -> None:
        if self._drag is None and self._moving:
            self._moving = False
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        if self.mesh is None:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                             tr("cad_preview.empty"))
            return
        # Сохраняем готовый кадр: перекрытие окна и лишние paint-события не
        # требуют повторной проекции и обхода десятков тысяч треугольников.
        ratio = self.devicePixelRatioF()
        width, height = max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))
        background = self.palette().base().color()
        rgb = (background.red(), background.green(), background.blue())
        fast = self._moving and self._fast_triangles is not self._triangles
        key = (width, height, ratio, rgb, self.yaw, self.elevation, self.zoom, fast)
        if key != self._frame_key:
            triangles = self._fast_triangles if fast else self._triangles
            shades = self._fast_shades if fast else self._shades
            image = rasterize(triangles, shades, self._center, self._radius, self.yaw, self.elevation,
                              self.zoom, width, height, rgb, margin=24 * ratio)
            data = image.tobytes()
            self._frame = QImage(data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
            self._frame_key = key
        if self._frame is not None:
            painter.drawImage(self.rect(), self._frame)
        if fast:
            painter.setPen(self.palette().text().color())
            painter.drawText(8, 20, tr("cad_preview.fast_view"))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._settle.stop()
            self._drag = event.position()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.position()
            delta, self._drag = current - self._drag, current
            self.yaw = remainder(self.yaw + delta.x() * 0.01, 2 * pi)
            self.elevation = max(-1.35, min(1.35, self.elevation + delta.y() * 0.01))
            self._moving = True
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = None
            self._finish_moving()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = max(-20., min(20., event.angleDelta().y() / 120.))
        if steps:
            self.zoom = max(0.25, min(4., self.zoom * 1.15 ** steps))
            self._moving = True
            self._settle.start()
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)
