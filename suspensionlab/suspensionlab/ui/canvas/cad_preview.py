"""Простой ортографический просмотр треугольных граней CAD без OpenGL."""
from __future__ import annotations

from math import pi, remainder

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QWidget

from ...core.cad_mesh import CadMesh, project_triangles
from ...i18n import tr


class CadPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 280)
        self.mesh: CadMesh | None = None
        self._shades = np.empty(0, dtype=np.int32)
        self._drag: QPointF | None = None
        self.reset_camera()

    def set_mesh(self, mesh: CadMesh | None) -> None:
        self.mesh = mesh
        if mesh is None:
            self._shades = np.empty(0, dtype=np.int32)
        else:
            triangles = mesh.triangles
            normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            sizes = np.linalg.norm(normals, axis=1)
            safe = np.maximum(sizes, 1e-20)
            intensity = np.abs(normals @ np.array([0.25, -0.45, 0.86]) / safe)
            self._shades = np.clip((intensity * 100 + 105).astype(np.int32), 105, 205)
        self.update()

    def reset_camera(self) -> None:
        self.yaw, self.elevation, self.zoom = -0.65, 0.35, 1.0
        self._drag = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        if self.mesh is None:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                             tr("cad_preview.empty"))
            return
        _, radius = self.mesh.bounds()
        scale = max(1., min(self.width() - 24, self.height() - 24)) / (2 * radius) * self.zoom
        projected, order = project_triangles(self.mesh, self.yaw, self.elevation)
        painter.setPen(Qt.PenStyle.NoPen)
        colors = [QColor(v * 3 // 4, v * 9 // 10, v) for v in range(256)]
        for index in order:
            coords = projected[index]
            points = QPolygonF([QPointF(self.width() / 2 + p[0] * scale, self.height() / 2 - p[1] * scale)
                                for p in coords])
            painter.setBrush(colors[int(self._shades[index])])
            painter.drawPolygon(points)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
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
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = max(-20., min(20., event.angleDelta().y() / 120.))
        if steps:
            self.zoom = max(0.25, min(4., self.zoom * 1.15 ** steps))
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)
