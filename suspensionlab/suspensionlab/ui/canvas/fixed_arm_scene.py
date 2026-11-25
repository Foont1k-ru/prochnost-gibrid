"""Вращаемый условный каркас рычага; только выбор точек, без редактирования опор."""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin
from typing import Any

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen

from ...core.pose_view import Point
from ...core.scene3d import Scene3D, Segment3D, project_orthographic
from ...model.fixed_arm_skeleton import SkeletonPreview
from .fixed_arm_pick import straight_leg_hits
from .scene3d_preview import Scene3DPreview

LABELS = {
    'lca_f_in': 'Передняя опора',
    'lca_r_in': 'Задняя опора',
    'lbj': 'Шаровая',
    'ball_housing_center': 'Центр корпуса',
    'bend_front': 'Вершина передней трубы',
    'bend_rear': 'Вершина задней трубы',
}


def skeleton_scene(preview: SkeletonPreview, bends: dict[str, dict[str, Any]], *,
                   show_ball_housing: bool = False) -> Scene3D:
    """Только проверенные осевые линии и явно введённые вершины изгиба."""
    segments = tuple(Segment3D(a, b, 'arm') for path in preview.centerlines
                     for a, b in zip(path, path[1:], strict=False))
    points: list[tuple[str, Point]] = list(zip(('lca_f_in', 'lca_r_in', 'lbj'), preview.anchors, strict=True))
    if show_ball_housing and preview.centerlines[0][-1] != preview.anchors[2]:
        points.append(('ball_housing_center', preview.centerlines[0][-1]))
    for leg in ('front', 'rear'):
        if leg in bends:
            vertex = bends[leg]['vertex_mm']
            points.append((f'bend_{leg}', (float(vertex[0]), float(vertex[1]), float(vertex[2]))))
    return Scene3D(0., segments, tuple(points))


@dataclass
class _VertexDrag:
    code: str
    point: Point
    start: QPointF
    current: QPointF
    scale: float
    yaw: float
    elevation: float
    size: tuple[int, int]
    moved: bool = False

    def candidate(self) -> Point:
        dx = (self.current.x() - self.start.x()) / self.scale
        dy = -(self.current.y() - self.start.y()) / self.scale
        cy, sy, ce, se = cos(self.yaw), sin(self.yaw), cos(self.elevation), sin(self.elevation)
        return (self.point[0] + dx * cy - dy * sy * se,
                self.point[1] + dx * sy + dy * cy * se,
                self.point[2] + dy * ce)


class FixedArmScene(Scene3DPreview):
    """Ортографическое вращение и выбор нарисованных маркеров; геометрия не меняется."""

    pointPicked = Signal(str)
    ambiguousPick = Signal()
    segmentPicked = Signal(str, object)
    dragStarted = Signal(str)
    dragMoved = Signal(str, object)
    dragReleased = Signal(str, object, object)
    dragCancelled = Signal()

    def __init__(self, parent=None, *, outer_label: str = 'Шаровая') -> None:
        super().__init__(parent, title_override='3D-скелет · условные осевые линии, не CAD',
                         legend_override='ЛКМ: вращение / перетащить вершину · ПКМ: сдвиг · колесо: масштаб')
        self._outer_label = outer_label
        self.paths: tuple[tuple[Point, ...], ...] = ()
        self._vertex_drag: _VertexDrag | None = None
        self._pick_start: QPointF | None = None
        self._pick_moved = False
        self.setAccessibleName('Трёхмерный условный скелет рычага')

    def _cancel_vertex_drag(self) -> None:
        if self._vertex_drag is not None:
            self._vertex_drag = None
            self.dragCancelled.emit()
            self.update()

    def set_scene(self, scene: Scene3D | None, paths: tuple[tuple[Point, ...], ...] = ()) -> None:
        self._cancel_vertex_drag()
        self.paths = paths
        self._pick_start = None
        self._pick_moved = False
        self.select_point(None)
        if scene is None:
            self.clear('Нет актуального скелета')
        else:
            self.configure([scene])
            self.show_frame(scene)

    def _screen_point(self, point: Point) -> QPointF:
        if self.bounds is None:
            raise ValueError('No bounds')
        center, radius = self.bounds
        scale = max(1.0, min(self.width() - 36, self.height() - 70)) / (2 * radius) * self.zoom
        x, y = project_orthographic(point, center, self.yaw, self.elevation)
        return QPointF(self.width() / 2 + self.pan_x + x * scale, self.height() / 2 + 8 + self.pan_y - y * scale)

    def _point_hits(self, position: QPointF) -> tuple[str, ...]:
        if self.frame is None or self.bounds is None:
            return ()
        # No depth inference: overlapping markers require explicit list selection.
        hits = []
        for code, point in self.frame.points:
            delta = self._screen_point(point) - position
            if delta.x() ** 2 + delta.y() ** 2 <= 12 ** 2:
                hits.append(code)
        return tuple(hits)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.frame is None or self.bounds is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for code, point in self.frame.points:
            position = self._screen_point(point)
            if not (0 <= position.x() < self.width() and 0 <= position.y() < self.height()):
                continue
            color = QColor('#ed9c2e' if code.startswith('bend_') else '#2da9b5')
            painter.setPen(QPen(color.darker(170), 1))
            painter.setBrush(color)
            painter.drawEllipse(position, 4, 4)
            painter.setPen(self.palette().text().color())
            label = self._outer_label if code == 'lbj' else LABELS[code]
            width = painter.fontMetrics().horizontalAdvance(label)
            x = position.x() + 7
            if x + width > self.width() - 6:
                x = position.x() - width - 7
            x = max(4., min(x, self.width() - width - 4.))
            y = max(18., min(position.y() - 7, self.height() - 32.))
            painter.drawText(QPointF(x, y), label)
        if self._vertex_drag is not None and self._vertex_drag.moved:
            ghost = self._screen_point(self._vertex_drag.candidate())
            painter.setPen(QPen(QColor('#df7620'), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(ghost, 7, 7)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._cancel_vertex_drag()
        if event.button() == Qt.MouseButton.LeftButton and self.frame is not None and self.bounds is not None:
            hits = self._point_hits(event.position())
            if len(hits) > 1:
                self.ambiguousPick.emit()
                event.accept()
                return
            if len(hits) == 1 and hits[0].startswith('bend_'):
                code = hits[0]
                point = self.frame.point(code)
                assert point is not None
                self.pointPicked.emit(code)
                scale = max(1.0, min(self.width() - 36, self.height() - 70)) / (2 * self.bounds[1]) * self.zoom
                self._vertex_drag = _VertexDrag(code, point, event.position(), event.position(), scale,
                                                self.yaw, self.elevation, (self.width(), self.height()))
                self.dragStarted.emit(code)
                self.setFocus()
                event.accept()
                return
            self._pick_start = event.position()
        else:
            self._pick_start = None
        self._pick_moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._vertex_drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._vertex_drag.current = event.position()
            if (event.position() - self._vertex_drag.start).manhattanLength() >= 6:
                self._vertex_drag.moved = True
                self.dragMoved.emit(self._vertex_drag.code, self._vertex_drag.candidate())
            self.update()
            event.accept()
            return
        if self._pick_start is not None and (event.position() - self._pick_start).manhattanLength() >= 6:
            self._pick_moved = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        drag = self._vertex_drag
        if drag is not None and event.button() == Qt.MouseButton.LeftButton:
            self._vertex_drag = None
            drag.current = event.position()
            scale = (max(1.0, min(self.width() - 36, self.height() - 70)) / (2 * self.bounds[1]) * self.zoom
                     if self.bounds is not None else 0.)
            if (drag.moved and drag.size == (self.width(), self.height()) and
                    drag.yaw == self.yaw and drag.elevation == self.elevation and drag.scale == scale and
                    (drag.current - drag.start).manhattanLength() >= 6):
                self.dragReleased.emit(drag.code, (0, 1, 2), drag.candidate())
            else:
                self.dragCancelled.emit()
            self.update()
            event.accept()
            return
        start, self._pick_start = self._pick_start, None
        if (start is not None and not self._pick_moved and event.button() == Qt.MouseButton.LeftButton and
                (event.position() - start).manhattanLength() < 6):
            hits = self._point_hits(event.position())
            if len(hits) == 1:
                self.pointPicked.emit(hits[0])
            elif len(hits) > 1:
                self.ambiguousPick.emit()
            elif self.paths:
                legs = straight_leg_hits(event.position(), self.paths, self._screen_point)
                if len(legs) == 1:
                    self.segmentPicked.emit(*legs[0])
                elif len(legs) > 1:
                    self.ambiguousPick.emit()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        self._cancel_vertex_drag()
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._vertex_drag is not None:
            self._cancel_vertex_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._cancel_vertex_drag()
        self._pick_start = None
        super().hideEvent(event)
