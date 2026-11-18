"""Ортографический просмотр дискретного каркаса без OpenGL и загрузки CAD."""
from __future__ import annotations

from math import pi, remainder

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ...core.camera_views import camera_view_angles
from ...core.pose_view import Point
from ...core.scene3d import Scene3D, Segment3D, project_orthographic, scene_bounds
from ...core.vehicle_schematic_visual import (
    JOINT_RADIUS_MM,
    SchematicVisual,
    VisualFace,
    VisualJoint,
    make_schematic_visual,
)
from ...i18n import tr

_COLORS = {"arm": "#3689e6", "knuckle": "#3689e6", "steering": "#bb8ce2", "spring": "#2ea86f",
           "damper": "#dd9748", "wheel": "#8a98a8"}


class Scene3DPreview(QWidget):
    """Только каркас рассчитанных точек, положение камеры не меняет проект."""

    def __init__(self, parent: QWidget | None = None, *, schematic: bool = False) -> None:
        super().__init__(parent)
        self.schematic = schematic
        self.volumetric = schematic
        self._visual: SchematicVisual | None = None
        self.setMinimumSize(300, 250)
        self.frame: Scene3D | None = None
        self.bounds: tuple[Point, float] | None = None
        self.message = tr("analysis.preview_empty")
        self.selected_point: str | None = None
        self.sample_positions: tuple[Point, ...] = ()
        self._drag: QPointF | None = None
        self._pan_drag: QPointF | None = None
        self._pan_button: Qt.MouseButton | None = None
        self.reset_camera()

    def reset_camera(self) -> None:
        self.yaw = -0.65
        self.elevation = 0.35
        self.zoom = 1.0
        self.pan_x, self.pan_y = 0., 0.
        self._drag = None
        self._pan_drag = None
        self._pan_button = None
        self.update()

    def set_standard_view(self, name: str) -> None:
        """Изменяет только направление, сохраняя масштаб и сдвиг."""
        yaw, elevation = camera_view_angles(name)
        self.yaw, self.elevation = yaw, elevation
        self._drag = None
        self._pan_drag = None
        self._pan_button = None
        self.update()

    def select_point(self, code: str | None) -> None:
        self.selected_point = code
        self.update()

    def set_sample_positions(self, points: tuple[Point, ...]) -> None:
        """Только дискретные положения, не соединяем и не интерполируем."""
        self.sample_positions = points
        self.update()

    def configure(self, frames: list[Scene3D]) -> None:
        self.bounds = scene_bounds(frames)
        self.update()

    def clear(self, message: str | None = None) -> None:
        self.frame = None
        self._visual = None
        self.bounds = None
        self.sample_positions = ()
        self.message = message or tr("analysis.preview_empty")
        self.update()

    def show_frame(self, frame: Scene3D | None, message: str | None = None) -> None:
        self.frame = frame
        self._visual = make_schematic_visual(frame) if self.schematic and frame is not None else None
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
        if self.schematic and self.volumetric and self._visual is not None:
            self._draw_schematic_volumes(painter, center, scale)
        else:
            for segment in self.frame.segments:
                a = project_orthographic(segment.start, center, self.yaw, self.elevation)
                b = project_orthographic(segment.end, center, self.yaw, self.elevation)
                painter.setPen(QPen(QColor(_COLORS[segment.kind]), 1.5 if segment.kind == "wheel" else 2.5))
                painter.drawLine(QPointF(self.width() / 2 + self.pan_x + a[0] * scale, self.height() / 2 + 8 + self.pan_y - a[1] * scale),
                                 QPointF(self.width() / 2 + self.pan_x + b[0] * scale, self.height() / 2 + 8 + self.pan_y - b[1] * scale))
        # Метки намеренно рисуются поверх линий, без проверки видимости/глубины.
        if self.sample_positions:
            painter.setPen(QPen(QColor("#00465a"), 1))
            painter.setBrush(QColor("#4dd8ef"))
            for sample in self.sample_positions:
                x, y = project_orthographic(sample, center, self.yaw, self.elevation)
                pos = QPointF(self.width() / 2 + self.pan_x + x * scale,
                              self.height() / 2 + 8 + self.pan_y - y * scale)
                painter.drawEllipse(pos, 3, 3)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        point = self.frame.point(self.selected_point) if self.selected_point else None
        if point is not None:
            x, y = project_orthographic(point, center, self.yaw, self.elevation)
            pos = QPointF(self.width() / 2 + self.pan_x + x * scale,
                          self.height() / 2 + 8 + self.pan_y - y * scale)
            painter.setPen(QPen(QColor("#211a00"), 2))
            painter.setBrush(QColor("#ffd43b"))
            painter.drawEllipse(pos, 6, 6)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.palette().text().color())
        painter.drawText(QRectF(8, 4, self.width() - 16, 22), int(Qt.AlignmentFlag.AlignLeft),
                         tr("vehicle_schematic.title") if self.schematic else
                         tr("analysis.scene3d.travel", travel=f"{self.frame.travel_mm:+.2f}"))
        painter.drawText(QRectF(8, self.height() - 26, self.width() - 16, 20), int(Qt.AlignmentFlag.AlignLeft),
                         tr("vehicle_schematic.legend") if self.schematic and self.volumetric else tr("analysis.scene3d.legend"))

    def _draw_schematic_volumes(self, painter: QPainter, center: Point, scale: float) -> None:
        """Условная заливка с приблизительной сортировкой по глубине, без CAD-рендера."""
        from math import cos, sin

        if self.frame is None or self._visual is None:
            return
        normal = (sin(self.yaw) * cos(self.elevation), -cos(self.yaw) * cos(self.elevation), sin(self.elevation))

        def depth(point: Point) -> float:
            return sum((point[i] - center[i]) * normal[i] for i in range(3))

        def screen(point: Point) -> QPointF:
            x, y = project_orthographic(point, center, self.yaw, self.elevation)
            return QPointF(self.width() / 2 + self.pan_x + x * scale, self.height() / 2 + 8 + self.pan_y - y * scale)

        # Все виды примитивов сортируются вместе; это иллюстрация, а не
        # точная проверка перекрытий и столкновений.
        items: list[tuple[float, VisualFace | VisualJoint | Segment3D]] = []
        for face in self._visual.faces:
            items.append((sum(depth(p) for p in face.vertices) / 3, face))
        for joint in self._visual.joints:
            items.append((depth(joint.center) + JOINT_RADIUS_MM, joint))
        for segment in self.frame.segments:
            if segment.kind not in ("arm", "steering"):
                items.append(((depth(segment.start) + depth(segment.end)) / 2, segment))
        items.sort(key=lambda item: item[0])
        painter.setPen(Qt.PenStyle.NoPen)
        for _, item in items:
            if isinstance(item, VisualFace):
                color = QColor(_COLORS[item.kind])
                color.setRgb(*(int(channel * item.shade) for channel in (color.red(), color.green(), color.blue())))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawPolygon(QPolygonF([screen(p) for p in item.vertices]))
            elif isinstance(item, VisualJoint):
                color = QColor(_COLORS[item.kind]).lighter(135)
                painter.setPen(QPen(color.darker(160), 1))
                painter.setBrush(color)
                painter.drawEllipse(screen(item.center), JOINT_RADIUS_MM * scale, JOINT_RADIUS_MM * scale)
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(_COLORS[item.kind]), 1.5 if item.kind == "wheel" else 2.5))
                painter.drawLine(screen(item.start), screen(item.end))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton) and self._drag is None and self._pan_drag is None:
            self._pan_drag = event.position()
            self._pan_button = event.button()
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton and self._pan_drag is None:
            self._drag = event.position()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pan_drag is not None and self._pan_button is not None and event.buttons() & self._pan_button:
            now = event.position()
            delta, self._pan_drag = now - self._pan_drag, now
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self.update()
            event.accept()
        elif self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            now = event.position()
            delta = now - self._drag
            self._drag = now
            self.yaw = remainder(self.yaw + delta.x() * 0.01, 2 * pi)
            self.elevation = remainder(self.elevation + delta.y() * 0.01, 2 * pi)
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pan_button is not None and event.button() == self._pan_button:
            self._pan_drag = None
            self._pan_button = None
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton and self._pan_drag is None:
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
