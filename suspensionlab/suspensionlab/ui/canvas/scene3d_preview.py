"""Ортографический просмотр дискретного каркаса без OpenGL и загрузки CAD."""
from __future__ import annotations

from math import pi, remainder

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...core.pose_view import Point
from ...core.scene3d import Scene3D, project_orthographic, scene_bounds
from ...i18n import tr

_COLORS = {"arm": "#3689e6", "knuckle": "#3689e6", "steering": "#bb8ce2", "spring": "#2ea86f",
           "damper": "#dd9748", "wheel": "#8a98a8"}


class Scene3DPreview(QWidget):
    """Только каркас рассчитанных точек, положение камеры не меняет проект."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 250)
        self.frame: Scene3D | None = None
        self.bounds: tuple[Point, float] | None = None
        self.message = tr("analysis.preview_empty")
        self._drag: QPointF | None = None
        self.reset_camera()

    def reset_camera(self) -> None:
        self.yaw = -0.65
        self.elevation = 0.35
        self.zoom = 1.0
        self._drag = None
        self.update()

    def configure(self, frames: list[Scene3D]) -> None:
        self.bounds = scene_bounds(frames)
        self.update()

    def clear(self, message: str | None = None) -> None:
        self.frame = None
        self.bounds = None
        self.message = message or tr("analysis.preview_empty")
        self.update()

    def show_frame(self, frame: Scene3D | None, message: str | None = None) -> None:
        self.frame = frame
        self.message = message or tr("analysis.preview_no_pose")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().text().color())
        if self.frame is None or self.bounds is None:
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), self.message)
            return
        center, radius = self.bounds
        scale = max(1.0, min(self.width() - 36, self.height() - 70)) / (2 * radius) * self.zoom
        for segment in self.frame.segments:
            a = project_orthographic(segment.start, center, self.yaw, self.elevation)
            b = project_orthographic(segment.end, center, self.yaw, self.elevation)
            painter.setPen(QPen(QColor(_COLORS[segment.kind]), 1.5 if segment.kind == "wheel" else 2.5))
            painter.drawLine(QPointF(self.width() / 2 + a[0] * scale, self.height() / 2 + 8 - a[1] * scale),
                             QPointF(self.width() / 2 + b[0] * scale, self.height() / 2 + 8 - b[1] * scale))
        painter.setPen(self.palette().text().color())
        painter.drawText(QRectF(8, 4, self.width() - 16, 22), int(Qt.AlignmentFlag.AlignLeft),
                         tr("analysis.scene3d.travel", travel=f"{self.frame.travel_mm:+.2f}"))
        painter.drawText(QRectF(8, self.height() - 26, self.width() - 16, 20), int(Qt.AlignmentFlag.AlignLeft),
                         tr("analysis.scene3d.legend"))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.position()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            now = event.position()
            delta = now - self._drag
            self._drag = now
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
        steps = event.angleDelta().y() / 120.0
        if steps:
            # Граница расчёта не позволяет редкому событию с огромной дельтой переполнить степень.
            self.zoom = max(0.25, min(4.0, self.zoom * (1.15 ** max(-20.0, min(20.0, steps)))))
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)
