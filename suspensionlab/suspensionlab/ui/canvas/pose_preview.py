"""Условная фронтальная проекция выбранного расчётного положения."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ...core.pose_view import Point, PoseView
from ...i18n import tr


class PosePreview(QWidget):
    """Отрисовывает данные выбранной строки; неподвижный масштаб на весь диапазон."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 250)
        self.frame: PoseView | None = None
        self.camber_deg = 0.0
        self.radius_mm = 0.0
        self.width_mm = 0.0
        self.side_sign = 1
        self.bounds: tuple[float, float, float, float] | None = None
        self.message = tr("analysis.preview_empty")

    def clear(self, message: str | None = None) -> None:
        self.frame = None
        self.bounds = None
        self.message = message or tr("analysis.preview_empty")
        self.update()

    def configure(self, frames: list[PoseView], radius: float, width: float) -> None:
        """Единые границы для всех решённых строк, чтобы схема не прыгала."""
        coords: list[Point] = []
        for frame in frames:
            coords.extend((frame.center, frame.upper_front, frame.upper_rear, frame.lower_front,
                           frame.lower_rear, frame.upper_ball, frame.lower_ball))
            if frame.spring:
                coords.extend(frame.spring)
            if frame.damper:
                coords.extend(frame.damper)
        self.radius_mm, self.width_mm = radius, width
        if not coords:
            self.bounds = None
            return
        # Радиус по обеим осям покрывает и повернутый условный контур колеса.
        extent = radius + width / 2
        ys = [p[1] for p in coords] + [f.center[1] + s * extent for f in frames for s in (-1, 1)]
        zs = [p[2] for p in coords] + [f.center[2] + s * extent for f in frames for s in (-1, 1)]
        self.bounds = (min(ys), max(ys), min(zs), max(zs))

    def show_frame(self, frame: PoseView, camber_deg: float, side_sign: int) -> None:
        self.frame, self.camber_deg, self.side_sign = frame, camber_deg, side_sign
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().text().color())
        if self.frame is None or self.bounds is None:
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), self.message)
            return
        y0, y1, z0, z1 = self.bounds
        scale = min((self.width() - 36) / max(y1 - y0, 1), (self.height() - 70) / max(z1 - z0, 1))
        yc, zc = (y0 + y1) / 2, (z0 + z1) / 2

        def screen(p: Point) -> QPointF:
            return QPointF(self.width() / 2 - (p[1] - yc) * scale,
                           self.height() / 2 + 8 - (p[2] - zc) * scale)

        frame = self.frame
        angle = math.radians(self.camber_deg)
        sy, sz = self.side_sign * math.sin(angle), math.cos(angle)
        wy, wz = math.cos(angle), -self.side_sign * math.sin(angle)
        cx, cy, cz = frame.center
        corners = [screen((cx, cy + a * sy * self.radius_mm + b * wy * self.width_mm / 2,
                           cz + a * sz * self.radius_mm + b * wz * self.width_mm / 2))
                   for a, b in ((-1, -1), (-1, 1), (1, 1), (1, -1))]
        painter.setPen(QPen(QColor("#8a98a8"), 2))
        painter.drawPolygon(QPolygonF(corners))
        painter.setPen(QPen(QColor("#3689e6"), 3))
        for start, end in ((frame.upper_front, frame.upper_ball), (frame.upper_rear, frame.upper_ball),
                           (frame.lower_front, frame.lower_ball), (frame.lower_rear, frame.lower_ball),
                           (frame.upper_ball, frame.lower_ball)):
            painter.drawLine(screen(start), screen(end))
        if frame.spring:
            self._draw_spring(painter, screen(frame.spring[0]), screen(frame.spring[1]))
        if frame.damper:
            painter.setPen(QPen(QColor("#dd9748"), 3))
            painter.drawLine(screen(frame.damper[0]), screen(frame.damper[1]))
        painter.setPen(self.palette().text().color())
        painter.drawText(QRectF(8, 4, self.width() - 16, 22), int(Qt.AlignmentFlag.AlignLeft),
                         tr("analysis.preview_travel", travel=f"{frame.travel_mm:+.2f}"))
        painter.drawText(QRectF(8, self.height() - 26, self.width() - 16, 20), int(Qt.AlignmentFlag.AlignLeft),
                         tr("analysis.preview_legend"))

    @staticmethod
    def _draw_spring(painter: QPainter, start: QPointF, end: QPointF) -> None:
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return
        nx, ny = -dy / length, dx / length
        path = QPainterPath(start)
        for i in range(1, 10):
            t = i / 10
            amplitude = min(5, length * 0.1) * (1 if i % 2 else -1)
            path.lineTo(start.x() + t * dx + amplitude * nx, start.y() + t * dy + amplitude * ny)
        path.lineTo(end)
        painter.setPen(QPen(QColor("#2ea86f"), 2))
        painter.drawPath(path)
