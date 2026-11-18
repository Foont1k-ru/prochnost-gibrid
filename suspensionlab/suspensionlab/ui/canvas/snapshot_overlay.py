"""Плоский просмотр двух наборов исходных точек; не CAD и не измерительный инструмент."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ...core.snapshot_compare import PointComparison
from ...core.snapshot_overlay import OverlayData
from ...i18n import tr


class SnapshotOverlayCanvas(QWidget):
    rowSelected = Signal(int)

    def __init__(self, rows: tuple[PointComparison, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows = rows
        self.data = OverlayData((), (), ())
        self.visible: frozenset[int] = frozenset()
        self.selected = -1
        self.zoom = 1.0
        self.setMinimumSize(360, 260)

    def set_data(self, data: OverlayData, visible: frozenset[int], selected: int = -1) -> None:
        self.data, self.visible, self.selected = data, visible, selected
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = zoom if zoom in (1.0, 2.0, 4.0, 8.0) else 1.0
        self.update()

    def screen_points(self) -> tuple[tuple[int, str, QPointF], ...]:
        """Масштаб по всем допустимым точкам оси, не меняется от фильтра состояния."""
        points = self.data.points
        if not points:
            return ()
        xmin, xmax = min(p.u for p in points), max(p.u for p in points)
        ymin, ymax = min(p.v for p in points), max(p.v for p in points)
        center_x, center_y = (xmin + xmax) / 2, (ymin + ymax) / 2
        selected = [p for p in points if p.row == self.selected]
        if self.zoom > 1 and selected:
            focus = next((p for p in selected if p.source == "B"), selected[0])
            center_x, center_y = focus.u, focus.v
        span_x, span_y = max(xmax - xmin, 1.0), max(ymax - ymin, 1.0)
        width, height = max(1., self.width() - 70.), max(1., self.height() - 70.)
        scale = min(width / span_x, height / span_y) * self.zoom
        return tuple((p.row, p.source, QPointF(self.width() / 2 + (p.u - center_x) * scale,
                                              self.height() / 2 - (p.v - center_y) * scale))
                     for p in points if p.row in self.visible)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRect(QRectF(12, 12, max(1, self.width() - 24), max(1, self.height() - 24)))
        points = self.screen_points()
        if not points:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                             tr("snapshot_overlay.empty"))
            return
        painter.setClipRect(QRectF(12, 12, max(1, self.width() - 24), max(1, self.height() - 24)))
        pairs: dict[int, dict[str, QPointF]] = {}
        for index, source, point in points:
            pairs.setdefault(index, {})[source] = point
        painter.setPen(QPen(self.palette().text().color(), 1.2))
        for index, pair in pairs.items():
            if index not in self.data.connected_rows or "A" not in pair or "B" not in pair:
                continue
            start, end = pair["A"], pair["B"]
            dx, dy = end.x() - start.x(), end.y() - start.y()
            length = math.hypot(dx, dy)
            if length <= 2:
                continue
            painter.drawLine(start, end)
            if length > 12:
                ux, uy = dx / length, dy / length
                tip = QPointF(end.x() - ux * 5, end.y() - uy * 5)
                left = QPointF(tip.x() - ux * 7 - uy * 3, tip.y() - uy * 7 + ux * 3)
                right = QPointF(tip.x() - ux * 7 + uy * 3, tip.y() - uy * 7 - ux * 3)
                painter.setBrush(self.palette().text())
                painter.drawPolygon(QPolygonF([tip, left, right]))
                painter.setBrush(Qt.BrushStyle.NoBrush)
        # Сначала A: полый квадрат остаётся видимым за маленьким кружком Б при совпадении.
        for source_kind in ("A", "B"):
            for index, source, point in points:
                if source != source_kind:
                    continue
                color = QColor("#378ce7") if source == "A" else QColor("#e78a27")
                painter.setPen(QPen(color, 2))
                if source == "A":
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(QRectF(point.x() - 6, point.y() - 6, 12, 12))
                else:
                    painter.setBrush(color)
                    painter.drawEllipse(point, 3.5, 3.5)
                if index == self.selected:
                    painter.setPen(QPen(self.palette().text().color(), 1.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(point, 10, 10)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not QRectF(12, 12, max(1, self.width() - 24), max(1, self.height() - 24)).contains(event.position()):
            return
        candidates = [(math.hypot(point.x() - event.position().x(), point.y() - event.position().y()), index)
                      for index, _source, point in self.screen_points()]
        if candidates:
            distance, index = min(candidates)
            if distance <= 12:
                self.rowSelected.emit(index)
                event.accept()
