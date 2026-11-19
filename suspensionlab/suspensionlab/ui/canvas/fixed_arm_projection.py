"""Ортогональная проекция скелета: перетаскивание только вершин изгиба."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ...core.pose_view import Point
from ...model.fixed_arm_skeleton import SkeletonPreview
from .fixed_arm_scene import LABELS


@dataclass
class _Drag:
    code: str
    point: Point
    start: QPointF
    current: QPointF
    scale: float
    size: tuple[int, int]
    moved: bool = False


class SkeletonProjection(QWidget):
    """При перетаскивании показывает призрак; кандидат принимается после отпускания."""

    pointPicked = Signal(str)
    ambiguousPick = Signal()
    dragStarted = Signal(str)
    dragCancelled = Signal()
    dragReleased = Signal(str, object, object)  # код, индексы осей, новые XYZ

    def __init__(self, axes: tuple[int, int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.axes = axes
        self.preview: SkeletonPreview | None = None
        self.points: tuple[tuple[str, Point], ...] = ()
        self.selected_point: str | None = None
        self._drag: _Drag | None = None
        self.setMinimumSize(380, 240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName('Проекция скелета ' + ''.join('XYZ'[i] for i in axes))

    def _cancel_drag(self) -> None:
        if self._drag is not None:
            self._drag = None
            self.dragCancelled.emit()
            self.update()

    def set_preview(self, preview: SkeletonPreview | None, points: tuple[tuple[str, Point], ...] = ()) -> None:
        self._cancel_drag()
        self.preview = preview
        self.points = points if preview is not None else ()
        self.selected_point = None
        self.update()

    def select_point(self, code: str | None) -> None:
        self.selected_point = code
        self.update()

    def _transform(self) -> tuple[float, float, float]:
        if self.preview is None:
            raise ValueError('Нет скелета')
        a, b = self.axes
        points = [p for path in self.preview.centerlines for p in path]
        points.extend(p for _, p in self.points)
        low_x, high_x = min(p[a] for p in points), max(p[a] for p in points)
        low_y, high_y = min(p[b] for p in points), max(p[b] for p in points)
        scale = min(max(self.width() - 100, 1) / max(high_x - low_x, 1),
                    max(self.height() - 80, 1) / max(high_y - low_y, 1))
        return (low_x + high_x) / 2, (low_y + high_y) / 2, scale

    def _screen_point(self, point: Point) -> QPointF:
        cx, cy, scale = self._transform()
        a, b = self.axes
        return QPointF(self.width() / 2 + (point[a] - cx) * scale,
                       self.height() / 2 - (point[b] - cy) * scale)

    def _point_hits(self, position: QPointF) -> tuple[str, ...]:
        if self.preview is None:
            return ()
        result = []
        for code, point in self.points:
            delta = self._screen_point(point) - position
            if delta.x() ** 2 + delta.y() ** 2 <= 12 ** 2:
                result.append(code)
        return tuple(result)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        if self.preview is None:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), 'Нет актуального скелета')
            return
        painter.setPen(QPen(QColor('#388aac'), 3))
        for path in self.preview.centerlines:
            painter.drawPolyline(QPolygonF([self._screen_point(p) for p in path]))
        for code, point in self.points:
            pos = self._screen_point(point)
            color = QColor('#ed9c2e' if code.startswith('bend_') else '#2da9b5')
            if self.selected_point == code:
                painter.setPen(QPen(QColor('#ffd43b'), 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(pos, 8, 8)
            painter.setPen(QPen(color.darker(170), 1))
            painter.setBrush(color)
            painter.drawEllipse(pos, 4, 4)
            painter.setPen(self.palette().text().color())
            label = LABELS[code]
            width = painter.fontMetrics().horizontalAdvance(label)
            x = pos.x() + 7
            if x + width > self.width() - 6:
                x = pos.x() - width - 7
            x = max(4., min(x, self.width() - width - 4.))
            y = max(18., min(pos.y() - 7, self.height() - 32.))
            painter.drawText(QPointF(x, y), label)
        if self._drag is not None and self._drag.moved:
            ghost = self._screen_point(self._drag.point) + self._drag.current - self._drag.start
            painter.setPen(QPen(QColor('#df7620'), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(ghost, 7, 7)
        painter.setPen(self.palette().text().color())
        plane = ''.join('XYZ'[i] for i in self.axes)
        painter.drawText(8, self.height() - 10, f'{plane}: перетащите оранжевую вершину · опоры закреплены')

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self.preview is None:
            self._cancel_drag()
            super().mousePressEvent(event)
            return
        self._cancel_drag()
        hits = self._point_hits(event.position())
        if len(hits) > 1:
            self.ambiguousPick.emit()
        elif len(hits) == 1:
            code = hits[0]
            self.pointPicked.emit(code)
            if code.startswith('bend_'):
                point = next(p for key, p in self.points if key == code)
                _, _, scale = self._transform()
                self._drag = _Drag(code, point, event.position(), event.position(), scale,
                                   (self.width(), self.height()))
                self.dragStarted.emit(code)
                self.setFocus()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag.current = event.position()
            if (self._drag.current - self._drag.start).manhattanLength() >= 4:
                self._drag.moved = True
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        drag = self._drag
        if event.button() != Qt.MouseButton.LeftButton or drag is None:
            super().mouseReleaseEvent(event)
            return
        self._drag = None
        self.update()
        if (drag.moved and drag.size == (self.width(), self.height()) and
                (event.position() - drag.start).manhattanLength() >= 4):
            delta = event.position() - drag.start
            candidate = list(drag.point)
            candidate[self.axes[0]] += delta.x() / drag.scale
            candidate[self.axes[1]] -= delta.y() / drag.scale
            self.dragReleased.emit(drag.code, self.axes, tuple(candidate))
        else:
            self.dragCancelled.emit()
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._drag is not None:
            self._cancel_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._cancel_drag()
        super().hideEvent(event)
