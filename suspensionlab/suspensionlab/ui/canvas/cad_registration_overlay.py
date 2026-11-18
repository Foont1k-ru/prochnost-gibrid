"""Схематические пары поверх предварительной CAD-сетки; глубина меток не учитывается."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from ...core.cad_raster import screen_projection
from ...core.cad_registration_overlay import OverlayPair
from .cad_preview import CadPreview


class RegistrationOverlayCanvas(CadPreview):
    def __init__(self, pairs: tuple[OverlayPair, ...], parent=None) -> None:
        super().__init__(parent)
        self.pairs = pairs
        self.visible: frozenset[int] = frozenset(range(len(pairs)))
        self.selected = -1

    def fit_overlay_bounds(self) -> None:
        if self.mesh is None:
            return
        vertices = self.mesh.triangles.reshape(-1, 3)
        points = np.asarray([p for pair in self.pairs for p in (pair.target, pair.transformed)], dtype=float)
        all_points = np.vstack((vertices, points))
        self._center = (all_points.min(axis=0) + all_points.max(axis=0)) / 2
        self._radius = max(float(np.linalg.norm(all_points - self._center, axis=1).max()), 1.)
        self._frame_key = None
        self.update()

    def positions(self) -> tuple[tuple[int, QPointF, QPointF], ...]:
        if self.mesh is None or not self.pairs:
            return ()
        points = np.asarray([p for pair in self.pairs for p in (pair.target, pair.transformed)], dtype=float)
        triangles = np.repeat(points[:, None, :], 3, axis=1)
        ratio = self.devicePixelRatioF()
        width, height = max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))
        screen, _ = screen_projection(triangles, self._center, self._radius, self.yaw, self.elevation,
                                      self.zoom, width, height, margin=24 * ratio,
                                      offset=self._pixel_offset(width, height))
        projected = [QPointF(float(p[0, 0]) * self.width() / width, float(p[0, 1]) * self.height() / height)
                     for p in screen]
        return tuple((i, projected[2 * i], projected[2 * i + 1])
                     for i in range(len(self.pairs)) if i in self.visible)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.mesh is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, target, transformed in self.positions():
            painter.setPen(QPen(self.palette().text().color(), 1.5))
            painter.drawLine(target, transformed)
            painter.setPen(QPen(QColor("#49a5ff"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(target.x() - 6, target.y() - 6, 12, 12))
            painter.setPen(QPen(QColor("#ff9b30"), 2))
            painter.setBrush(QColor("#ff9b30"))
            painter.drawEllipse(transformed, 3.5, 3.5)
            if index == self.selected:
                painter.setPen(QPen(self.palette().text().color(), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(target, 11, 11)
            painter.setPen(self.palette().text().color())
            painter.drawText(target + QPointF(8, -8), str(index + 1))
