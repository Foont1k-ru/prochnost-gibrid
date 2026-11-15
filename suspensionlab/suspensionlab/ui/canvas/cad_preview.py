"""Ортографический просмотр CAD без OpenGL; быстрый вид при движении камеры."""
from __future__ import annotations

from math import pi, remainder

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from ...core.cad_interaction import interaction_geometry
from ...core.cad_mesh import CadMesh
from ...core.cad_raster import pick_triangle, rasterize, triangle_shades
from ...i18n import tr


class CadPreview(QWidget):
    triangle_picked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 280)
        self.mesh: CadMesh | None = None
        self._triangles = np.empty((0, 3, 3))
        self._fast_triangles = self._triangles
        self._shades = np.empty(0, dtype=np.uint8)
        self._fast_shades = self._shades
        self._highlight: np.ndarray | None = None
        self._fast_highlight: np.ndarray | None = None
        self._through = False
        self._center = np.zeros(3)
        self._radius = 1.
        self._drag: QPointF | None = None
        self._press: QPointF | None = None
        self._dragging = False
        self._pick_allowed = False
        self._moving = False
        self._frame_key: tuple | None = None
        self._frame: QImage | None = None
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(200)
        self._settle.timeout.connect(self._finish_moving)
        self.reset_camera()

    def set_mesh(self, mesh: CadMesh | None, highlight: np.ndarray | None = None, through: bool = False) -> None:
        if highlight is not None:
            if mesh is None or highlight.shape != (len(mesh.triangles),) or highlight.dtype.kind != "b":
                raise ValueError("Некорректная маска подсветки")
            highlight = np.array(highlight, dtype=bool, copy=True)
            highlight.flags.writeable = False
        self._highlight = highlight
        self._through = bool(through and highlight is not None)
        self.mesh = mesh
        self._settle.stop()
        self._moving = False
        self._drag = None
        self._press = None
        self._dragging = False
        self._frame_key = None
        self._frame = None
        if mesh is None:
            self._triangles = np.empty((0, 3, 3))
            self._fast_triangles = self._triangles
            self._shades = np.empty(0, dtype=np.uint8)
            self._fast_shades = self._shades
            self._fast_highlight = None
        else:
            self._triangles = mesh.triangles
            self._center, self._radius = mesh.bounds()
            self._shades = triangle_shades(self._triangles)
            self._fast_triangles, self._fast_highlight = interaction_geometry(mesh, highlight)
            self._fast_shades = (self._shades if self._fast_triangles is self._triangles
                                 else triangle_shades(self._fast_triangles))
        self.update()

    def reset_camera(self) -> None:
        self.yaw, self.elevation, self.zoom = -0.65, 0.35, 1.0
        self._drag = None
        self._press = None
        self._dragging = False
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
            highlight = self._fast_highlight if fast else self._highlight
            image = rasterize(triangles, shades, self._center, self._radius, self.yaw, self.elevation,
                              self.zoom, width, height, rgb, margin=24 * ratio,
                              highlight=highlight, through=self._through)
            data = image.tobytes()
            self._frame = QImage(data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
            self._frame_key = key
        if self._frame is not None:
            painter.drawImage(self.rect(), self._frame)
        if fast or self._through:
            painter.setPen(self.palette().text().color())
            if fast:
                painter.drawText(8, 20, tr("cad_preview.fast_view"))
            if self._through:
                painter.drawText(8, 40 if fast else 20, tr("cad_preview.through_view"))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._settle.stop()
            self._drag = self._press = event.position()
            self._dragging = False
            # Нельзя выбирать по упрощённому кадру с другой геометрией.
            self._pick_allowed = not self._moving or self._fast_triangles is self._triangles
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.position()
            if not self._dragging:
                if (current - self._press).manhattanLength() < QApplication.startDragDistance():
                    event.accept()
                    return
                self._dragging = True
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
            position = event.position()
            clicked = (self._press is not None and not self._dragging and self._pick_allowed and
                       (position - self._press).manhattanLength() < QApplication.startDragDistance())
            self._drag = self._press = None
            self._dragging = False
            self._finish_moving()
            if (clicked and self.mesh is not None and self.mesh.triangle_parts is not None and
                    0 <= position.x() < self.width() and 0 <= position.y() < self.height()):
                ratio = self.devicePixelRatioF()
                width, height = max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))
                x = int(position.x() * width / max(1, self.width()))
                y = int(position.y() * height / max(1, self.height()))
                index = pick_triangle(self._triangles, self._center, self._radius, self.yaw, self.elevation,
                                      self.zoom, width, height, x, y, margin=24 * ratio,
                                      highlight=self._highlight, through=self._through)
                if index is not None:
                    self.triangle_picked.emit(index)
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
