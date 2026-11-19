"""Вращаемый условный каркас рычага; только выбор точек, без редактирования опор."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen

from ...core.pose_view import Point
from ...core.scene3d import Scene3D, Segment3D, project_orthographic
from ...model.fixed_arm_skeleton import SkeletonPreview
from .scene3d_preview import Scene3DPreview

LABELS = {
    'lca_f_in': 'Передняя опора',
    'lca_r_in': 'Задняя опора',
    'lbj': 'Шаровая',
    'bend_front': 'Вершина передней трубы',
    'bend_rear': 'Вершина задней трубы',
}


def skeleton_scene(preview: SkeletonPreview, bends: dict[str, dict[str, Any]]) -> Scene3D:
    """Только проверенные осевые линии и явно введённые вершины изгиба."""
    segments = tuple(Segment3D(a, b, 'arm') for path in preview.centerlines
                     for a, b in zip(path, path[1:], strict=False))
    points: list[tuple[str, Point]] = list(zip(('lca_f_in', 'lca_r_in', 'lbj'), preview.anchors, strict=True))
    for leg in ('front', 'rear'):
        if leg in bends:
            vertex = bends[leg]['vertex_mm']
            points.append((f'bend_{leg}', (float(vertex[0]), float(vertex[1]), float(vertex[2]))))
    return Scene3D(0., segments, tuple(points))


class FixedArmScene(Scene3DPreview):
    """Ортографическое вращение и выбор нарисованных маркеров; геометрия не меняется."""

    pointPicked = Signal(str)
    ambiguousPick = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title_override='3D-скелет · условные осевые линии, не CAD',
                         legend_override='ЛКМ: вращение / выбор точки · ПКМ: сдвиг · колесо: масштаб')
        self._pick_start: QPointF | None = None
        self._pick_moved = False
        self.setAccessibleName('Трёхмерный условный скелет рычага')

    def set_scene(self, scene: Scene3D | None) -> None:
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
            label = LABELS[code]
            width = painter.fontMetrics().horizontalAdvance(label)
            x = position.x() + 7
            if x + width > self.width() - 6:
                x = position.x() - width - 7
            x = max(4., min(x, self.width() - width - 4.))
            y = max(18., min(position.y() - 7, self.height() - 32.))
            painter.drawText(QPointF(x, y), label)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.frame is not None:
            self._pick_start = event.position()
        else:
            self._pick_start = None
        self._pick_moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pick_start is not None and (event.position() - self._pick_start).manhattanLength() >= 6:
            self._pick_moved = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        start, self._pick_start = self._pick_start, None
        if (start is not None and not self._pick_moved and event.button() == Qt.MouseButton.LeftButton and
                (event.position() - start).manhattanLength() < 6):
            hits = self._point_hits(event.position())
            if len(hits) == 1:
                self.pointPicked.emit(hits[0])
            elif len(hits) > 1:
                self.ambiguousPick.emit()
        super().mouseReleaseEvent(event)
