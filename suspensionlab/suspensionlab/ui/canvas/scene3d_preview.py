"""Ортографический просмотр дискретного каркаса без OpenGL и загрузки CAD."""
from __future__ import annotations

from math import pi, remainder

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ...core.camera_views import camera_view_angles
from ...core.pose_view import Point
from ...core.scene3d import Scene3D, Segment3D, project_orthographic, scene_bounds
from ...core.vehicle_schematic_pick import LinkHit, projected_link_hits
from ...core.vehicle_schematic_scene import SelectableLink
from ...core.vehicle_schematic_visual import (
    JOINT_RADIUS_MM,
    SchematicVisual,
    VisualFace,
    VisualJoint,
    make_schematic_visual,
)
from ...i18n import tr

_COLORS = {"arm": "#3689e6", "knuckle": "#3689e6", "steering": "#bb8ce2", "spring": "#2ea86f",
           "damper": "#dd9748", "wheel": "#8a98a8", "rod": "#e1ca58", "rocker": "#f07b83"}


class Scene3DPreview(QWidget):
    """Только каркас рассчитанных точек, положение камеры не меняет проект."""

    linksClicked = Signal(object, object)
    pointsClicked = Signal(object, object)
    pointDragged = Signal(str, object, float, float)

    def __init__(self, parent: QWidget | None = None, *, schematic: bool = False,
                 title_override: str | None = None, legend_override: str | None = None) -> None:
        super().__init__(parent)
        self.schematic = schematic
        self.title_override = title_override
        self.legend_override = legend_override
        self.volumetric = schematic
        self._visual: SchematicVisual | None = None
        self.link_targets: tuple[SelectableLink, ...] = ()
        # Opt-in: other schematic previews retain their existing click behaviour.
        self.point_selection_enabled = False
        self.editable_point_codes: frozenset[str] = frozenset()
        self.point_drag_enabled = False
        self._point_drag: tuple[str, Scene3D, QPointF, float] | None = None
        self._point_drag_pos: QPointF | None = None
        self.selected_link: tuple[str, str] | None = None
        self._click_press: QPointF | None = None
        self._click_moved = False
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

    def cancel_point_drag(self) -> None:
        self._point_drag = None
        self._point_drag_pos = None
        self.update()

    def reset_camera(self) -> None:
        self.cancel_point_drag()
        self.yaw = -0.65
        self.elevation = 0.35
        self.zoom = 1.0
        self.pan_x, self.pan_y = 0., 0.
        self._drag = None
        self._click_press = None
        self._pan_drag = None
        self._pan_button = None
        self.update()

    def set_standard_view(self, name: str) -> None:
        """Изменяет только направление, сохраняя масштаб и сдвиг."""
        self.cancel_point_drag()
        yaw, elevation = camera_view_angles(name)
        self.yaw, self.elevation = yaw, elevation
        self._drag = None
        self._click_press = None
        self._pan_drag = None
        self._pan_button = None
        self.update()

    def select_point(self, code: str | None) -> None:
        if code != self.selected_point:
            self.cancel_point_drag()
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
        self.cancel_point_drag()
        self.frame = None
        self._visual = None
        self.link_targets = ()
        self.bounds = None
        self.sample_positions = ()
        self.message = message or tr("analysis.preview_empty")
        self.update()

    def show_frame(self, frame: Scene3D | None, message: str | None = None) -> None:
        if frame is not self.frame:
            self.cancel_point_drag()
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
        self._draw_selected_link(painter, center, scale)
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
        if self.point_selection_enabled:
            painter.setPen(QPen(QColor('#173750'), 1))
            painter.setBrush(QColor('#b9e5ff'))
            for code, position in self.frame.points:
                if code in self.editable_point_codes:
                    x, y = project_orthographic(position, center, self.yaw, self.elevation)
                    painter.drawEllipse(QPointF(self.width() / 2 + self.pan_x + x * scale,
                                                self.height() / 2 + 8 + self.pan_y - y * scale), 3.5, 3.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        point = self.frame.point(self.selected_point) if self.selected_point else None
        if point is not None:
            x, y = project_orthographic(point, center, self.yaw, self.elevation)
            pos = QPointF(self.width() / 2 + self.pan_x + x * scale,
                          self.height() / 2 + 8 + self.pan_y - y * scale)
            painter.setPen(QPen(QColor("#211a00"), 2))
            painter.setBrush(QColor("#ffd43b"))
            painter.drawEllipse(pos, 6, 6)
            if self._point_drag is not None and self._point_drag_pos is not None:
                delta = self._point_drag_pos - self._point_drag[2]
                painter.setPen(QPen(QColor('#d48700'), 2, Qt.PenStyle.DashLine))
                painter.drawLine(pos, pos + delta)
                painter.setBrush(QColor('#ffb83b'))
                painter.drawEllipse(pos + delta, 6, 6)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.palette().text().color())
        painter.drawText(QRectF(8, 4, self.width() - 16, 22), int(Qt.AlignmentFlag.AlignLeft),
                         self.title_override if self.title_override is not None else
                         tr("vehicle_schematic.title") if self.schematic else
                         tr("analysis.scene3d.travel", travel=f"{self.frame.travel_mm:+.2f}"))
        painter.drawText(QRectF(8, self.height() - 26, self.width() - 16, 20), int(Qt.AlignmentFlag.AlignLeft),
                         self.legend_override if self.legend_override is not None else
                         tr("vehicle_schematic.legend") if self.schematic and self.volumetric else tr("analysis.scene3d.legend"))

    def _draw_selected_link(self, painter: QPainter, center: Point, scale: float) -> None:
        """Подсветка поверх сцены, не проверка видимости."""
        if not self.schematic or self.selected_link is None:
            return
        pen = QPen(QColor("#ffe04a"), 3.5)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        for target in self.link_targets:
            if (target.role, target.code) != self.selected_link:
                continue
            a, b = (project_orthographic(p, center, self.yaw, self.elevation)
                    for p in (target.segment.start, target.segment.end))
            painter.drawLine(QPointF(self.width() / 2 + self.pan_x + a[0] * scale,
                                     self.height() / 2 + 8 + self.pan_y - a[1] * scale),
                             QPointF(self.width() / 2 + self.pan_x + b[0] * scale,
                                     self.height() / 2 + 8 + self.pan_y - b[1] * scale))

    def _link_hits(self, position: QPointF) -> tuple[LinkHit, ...]:
        if self.bounds is None or self.frame is None:
            return ()
        center, radius = self.bounds
        scale = max(1.0, min(self.width() - 36, self.height() - 70)) / (2 * radius) * self.zoom
        return projected_link_hits(
            self.link_targets, center=center, yaw=self.yaw, elevation=self.elevation, scale=scale,
            origin=(self.width() / 2 + self.pan_x, self.height() / 2 + 8 + self.pan_y),
            click=(position.x(), position.y()),
            tolerance_px=max(7., JOINT_RADIUS_MM * scale + 5. if self.volumetric else 7.),
        )

    def _point_hits(self, position: QPointF) -> tuple[str, ...]:
        """Projected candidates, not a depth or visibility test."""
        if self.bounds is None or self.frame is None or not self.point_selection_enabled:
            return ()
        center, radius = self.bounds
        scale = max(1.0, min(self.width() - 36, self.height() - 70)) / (2 * radius) * self.zoom
        hits = []
        for code, point in self.frame.points:
            if code not in self.editable_point_codes:
                continue
            x, y = project_orthographic(point, center, self.yaw, self.elevation)
            dx = self.width() / 2 + self.pan_x + x * scale - position.x()
            dy = self.height() / 2 + 8 + self.pan_y - y * scale - position.y()
            distance = dx * dx + dy * dy
            if distance <= 9 ** 2:
                hits.append((distance, code))
        return tuple(code for _, code in sorted(hits))

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
        if (self.point_drag_enabled and event.button() == Qt.MouseButton.LeftButton and
                not event.modifiers() & Qt.KeyboardModifier.ShiftModifier and
                self.frame is not None and self.bounds is not None and self.selected_point is not None and
                self.selected_point in self._point_hits(event.position()) and
                abs(self.yaw) < 1e-9 and abs(self.elevation - pi / 2) < 1e-9):
            scale = max(1.0, min(self.width() - 36, self.height() - 70)) / (2 * self.bounds[1]) * self.zoom
            self._point_drag = (self.selected_point, self.frame, event.position(), scale)
            self._point_drag_pos = event.position()
            self.setFocus()
            event.accept()
        elif event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton) and self._drag is None and self._pan_drag is None:
            self._pan_drag = event.position()
            self._pan_button = event.button()
            event.accept()
        elif (self.point_drag_enabled and event.button() == Qt.MouseButton.LeftButton and
              not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            event.accept()  # In edit mode a blank drag must not rotate the plane.
        elif event.button() == Qt.MouseButton.LeftButton and self._pan_drag is None:
            self._drag = event.position()
            self._click_press = event.position() if self.schematic else None
            self._click_moved = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._point_drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._point_drag_pos = event.position()
            self.update()
            event.accept()
        elif self._pan_drag is not None and self._pan_button is not None and event.buttons() & self._pan_button:
            now = event.position()
            delta, self._pan_drag = now - self._pan_drag, now
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self.update()
            event.accept()
        elif self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            now = event.position()
            if self._click_press is not None and not self._click_moved:
                if (now - self._click_press).manhattanLength() < 6:
                    event.accept()
                    return
                self._click_moved = True
            delta = now - self._drag
            self._drag = now
            if self.point_drag_enabled:
                event.accept()
                return
            self.yaw = remainder(self.yaw + delta.x() * 0.01, 2 * pi)
            self.elevation = remainder(self.elevation + delta.y() * 0.01, 2 * pi)
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._point_drag is not None and event.button() == Qt.MouseButton.LeftButton:
            code, frame, start, scale = self._point_drag
            delta = event.position() - start
            self.cancel_point_drag()
            if delta.manhattanLength() >= 6:
                # Top view projects +X right and +Y up; Z is held fixed.
                self.pointDragged.emit(code, frame, delta.x() / scale, -delta.y() / scale)
            event.accept()
        elif self._pan_button is not None and event.button() == self._pan_button:
            self._pan_drag = None
            self._pan_button = None
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton and self._pan_drag is None:
            if (self._click_press is not None and not self._click_moved and
                    (event.position() - self._click_press).manhattanLength() < 6):
                if self.point_selection_enabled and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    point_hits = self._point_hits(event.position())
                    if point_hits:
                        self.pointsClicked.emit(point_hits, event.position().toPoint())
                else:
                    hits = self._link_hits(event.position())
                    if hits:
                        self.linksClicked.emit(hits, event.position().toPoint())
            self._click_press = None
            self._drag = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._point_drag is not None:
            self.cancel_point_drag()
            event.accept()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.cancel_point_drag()
        super().resizeEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.cancel_point_drag()
        super().focusOutEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.cancel_point_drag()
        super().hideEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._point_drag is not None:
            event.accept()
            return
        steps = event.angleDelta().y() / 120.0
        if steps:
            # Граница расчёта не позволяет редкому событию с огромной дельтой переполнить степень.
            self.zoom = max(0.25, min(4.0, self.zoom * (1.15 ** max(-20.0, min(20.0, steps)))))
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)
