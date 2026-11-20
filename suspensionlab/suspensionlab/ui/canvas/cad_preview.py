"""Ортографический CAD-просмотр: CPU и экспериментальный OpenGL по запросу."""
from __future__ import annotations

from math import pi, remainder
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from ...core.cad_interaction import interaction_geometry
from ...core.cad_measurement import point_on_projected_triangle
from ...core.cad_mesh import CadMesh
from ...core.cad_raster import pick_triangle, rasterize, screen_projection, triangle_shades
from ...core.camera_views import camera_view_angles
from ...i18n import tr

if TYPE_CHECKING:
    from .cad_gl_renderer import CadGlRenderer


class CadPreview(QWidget):
    triangle_picked = Signal(int)
    point_picked = Signal(object)
    point_missed = Signal()

    def __init__(self, parent: QWidget | None = None, *, empty_text_key: str = "cad_preview.empty") -> None:
        super().__init__(parent)
        self._empty_text_key = empty_text_key
        self.setMinimumSize(320, 280)
        self.mesh: CadMesh | None = None
        self._triangles = np.empty((0, 3, 3))
        self._fast_triangles = self._triangles
        self._shades = np.empty(0, dtype=np.uint8)
        self._fast_shades = self._shades
        self._highlight: np.ndarray | None = None
        self._fast_highlight: np.ndarray | None = None
        self._through = False
        self._measure_mode = False
        self._markers: tuple[tuple[float, float, float], ...] = ()
        self._center = np.zeros(3)
        self._radius = 1.
        self._drag: QPointF | None = None
        self._press: QPointF | None = None
        self._pan_drag: QPointF | None = None
        self._pan_button: Qt.MouseButton | None = None
        self._dragging = False
        self._pick_allowed = False
        self._moving = False
        self._frame_key: tuple | None = None
        self._frame: QImage | None = None
        self._gpu: CadGlRenderer | None = None
        self._mesh_revision = 0
        self._gpu_revision = -1
        self._renderer_button = QPushButton(tr("cad_preview.renderer_cpu"), self)
        self._renderer_button.setCheckable(True)
        self._renderer_button.setToolTip(tr("cad_preview.renderer_cpu_tip"))
        self._renderer_button.setAccessibleName(tr("cad_preview.renderer_cpu_tip"))
        self._renderer_button.toggled.connect(self._renderer_toggled)
        self._renderer_button.adjustSize()
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(200)
        self._settle.timeout.connect(self._finish_moving)
        self.reset_camera()

    def set_mesh(self, mesh: CadMesh | None, highlight: np.ndarray | None = None, through: bool = False) -> None:
        if highlight is not None:
            if mesh is None or highlight.shape != (len(mesh.triangles),) or highlight.dtype.kind != "b":
                raise ValueError("Некорректная маска подсветки")
            highlight = np.array(highlight, dtype=bool, copy=True)
            highlight.flags.writeable = False
        self._mesh_revision += 1
        self._highlight = highlight
        self._through = bool(through and highlight is not None)
        self.mesh = mesh
        self._settle.stop()
        self._moving = False
        self._drag = None
        self._press = None
        self._pan_drag = None
        self._pan_button = None
        self._dragging = False
        self._frame_key = None
        self._frame = None
        if mesh is None:
            self._close_gpu()
            if self._renderer_button.isChecked():
                self._renderer_button.setToolTip(tr("cad_preview.renderer_gl_wait"))
            self._triangles = np.empty((0, 3, 3))
            self._fast_triangles = self._triangles
            self._shades = np.empty(0, dtype=np.uint8)
            self._fast_shades = self._shades
            self._fast_highlight = None
        else:
            self._triangles = mesh.triangles
            self._center, self._radius = mesh.bounds()
            self._shades = triangle_shades(self._triangles)
            self._fast_triangles, self._fast_highlight = interaction_geometry(mesh, highlight)
            self._fast_shades = (self._shades if self._fast_triangles is self._triangles
                                 else triangle_shades(self._fast_triangles))
        self.update()

    def _renderer_toggled(self, enabled: bool) -> None:
        self._frame_key = None
        self._frame = None
        if enabled:
            self._renderer_button.setText(tr("cad_preview.renderer_gl"))
            self._renderer_button.setToolTip(tr("cad_preview.renderer_gl_wait"))
        else:
            self._close_gpu()
            self._renderer_button.setText(tr("cad_preview.renderer_cpu"))
            self._renderer_button.setToolTip(tr("cad_preview.renderer_cpu_tip"))
        self._renderer_button.adjustSize()
        self._position_renderer_button()
        self.update()

    def _position_renderer_button(self) -> None:
        self._renderer_button.move(max(0, self.width() - self._renderer_button.width() - 8), 8)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_renderer_button()

    def _close_gpu(self) -> None:
        gpu, self._gpu = self._gpu, None
        self._gpu_revision = -1
        if gpu is not None:
            gpu.close()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._close_gpu()
        self._frame_key = None
        super().hideEvent(event)

    def _gpu_failed(self, error: Exception) -> None:
        self._renderer_button.setChecked(False)
        reason = str(error).replace("\n", " ")[:300] or type(error).__name__
        self._renderer_button.setToolTip(tr("cad_preview.renderer_failed", reason=reason))
        self._frame_key = None
        self._frame = None

    def _get_gpu(self) -> CadGlRenderer:
        if self._gpu is None:
            from .cad_gl_renderer import CadGlRenderer

            self._gpu = CadGlRenderer()
            self._renderer_button.setToolTip(tr("cad_preview.renderer_gl_tip", vendor=self._gpu.vendor,
                                                renderer=self._gpu.renderer, version=self._gpu.version))
        if self._gpu_revision != self._mesh_revision:
            assert self.mesh is not None
            self._gpu.set_mesh(self.mesh, self._center, self._radius, self._shades, self._highlight)
            self._gpu_revision = self._mesh_revision
        return self._gpu

    def set_measure_mode(self, enabled: bool) -> None:
        self._measure_mode = enabled

    def set_markers(self, points: tuple[tuple[float, float, float], ...]) -> None:
        if len(points) > 2 or any(len(point) != 3 or not all(np.isfinite(v) for v in point) for point in points):
            raise ValueError("Некорректные метки")
        self._markers = tuple((float(p[0]), float(p[1]), float(p[2])) for p in points)
        self.update()

    def reset_camera(self) -> None:
        self.yaw, self.elevation, self.zoom = -0.65, 0.35, 1.0
        self.pan_x, self.pan_y = 0., 0.
        self._drag = None
        self._press = None
        self._pan_drag = None
        self._pan_button = None
        self._dragging = False
        self._settle.stop()
        self._moving = False
        self.update()

    def set_standard_view(self, name: str) -> None:
        """Изменяет направление в системе координат сетки, не её положение."""
        yaw, elevation = camera_view_angles(name)
        self.yaw, self.elevation = yaw, elevation
        self._drag = None
        self._press = None
        self._pan_drag = None
        self._pan_button = None
        self._dragging = False
        self._pick_allowed = False
        self._settle.stop()
        self._moving = False
        self.update()

    def _finish_moving(self) -> None:
        if self._drag is None and self._pan_drag is None and self._moving:
            self._moving = False
            self.update()

    def _pixel_offset(self, width: int, height: int) -> tuple[float, float]:
        return self.pan_x * width / max(1, self.width()), self.pan_y * height / max(1, self.height())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        if self.mesh is None:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                             tr(self._empty_text_key))
            return
        # Сохраняем готовый кадр: перекрытие окна и лишние paint-события не
        # требуют повторной проекции и обхода десятков тысяч треугольников.
        ratio = self.devicePixelRatioF()
        width, height = max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))
        background = self.palette().base().color()
        rgb = (background.red(), background.green(), background.blue())
        fast = self._moving and self._fast_triangles is not self._triangles and not self._renderer_button.isChecked()
        offset = self._pixel_offset(width, height)
        key = (width, height, ratio, rgb, self.yaw, self.elevation, self.zoom, fast, offset,
               self._renderer_button.isChecked())
        if key != self._frame_key:
            if self._renderer_button.isChecked():
                try:
                    gpu = self._get_gpu()
                    self._frame = gpu.render(self._center, self.yaw, self.elevation, self.zoom, width, height,
                                             24 * ratio, offset, self._highlight, self._through, rgb)
                except Exception as error:
                    self._gpu_failed(error)
            if not self._renderer_button.isChecked():
                fast = self._moving and self._fast_triangles is not self._triangles
                triangles = self._fast_triangles if fast else self._triangles
                shades = self._fast_shades if fast else self._shades
                highlight = self._fast_highlight if fast else self._highlight
                image = rasterize(triangles, shades, self._center, self._radius, self.yaw, self.elevation,
                                  self.zoom, width, height, rgb, margin=24 * ratio,
                                  highlight=highlight, through=self._through, offset=offset)
                data = image.tobytes()
                self._frame = QImage(data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
                key = (width, height, ratio, rgb, self.yaw, self.elevation, self.zoom, fast, offset, False)
            self._frame_key = key
        if self._frame is not None:
            painter.drawImage(self.rect(), self._frame)
        if self._markers:
            marker_triangles = np.repeat(np.asarray(self._markers)[:, None, :], 3, axis=1)
            screen, _ = screen_projection(marker_triangles, self._center, self._radius, self.yaw, self.elevation,
                                          self.zoom, width, height, margin=24 * ratio, offset=offset)
            positions = [QPointF(float(p[0, 0]) * self.width() / width, float(p[0, 1]) * self.height() / height)
                         for p in screen]
            pen = QPen(QColor(245, 55, 45), 2)
            painter.setPen(pen)
            if len(positions) == 2:
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(positions[0], positions[1])
                pen.setStyle(Qt.PenStyle.SolidLine)
                painter.setPen(pen)
            painter.setBrush(QColor(255, 245, 125))
            for label, pos in zip(("A", "B"), positions, strict=False):
                painter.drawEllipse(pos, 5, 5)
                painter.drawText(pos + QPointF(7, -6), label)
        if fast or self._through or self._markers:
            painter.setPen(self.palette().text().color())
            line = 20
            if fast:
                painter.drawText(8, line, tr("cad_preview.fast_view"))
                line += 20
            if self._through:
                painter.drawText(8, line, tr("cad_preview.through_view"))
                line += 20
            if self._markers:
                painter.drawText(8, line, tr("cad_preview.measure_overlay"))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton) and self._drag is None and self._pan_drag is None:
            self._settle.stop()
            self._pan_drag = event.position()
            self._pan_button = event.button()
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton and self._pan_drag is None:
            self._settle.stop()
            self._drag = self._press = event.position()
            self._dragging = False
            # Нельзя выбирать по упрощённому кадру с другой геометрией.
            self._pick_allowed = not self._moving or self._fast_triangles is self._triangles
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pan_drag is not None and self._pan_button is not None and event.buttons() & self._pan_button:
            current = event.position()
            delta, self._pan_drag = current - self._pan_drag, current
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self._moving = True
            self.update()
            event.accept()
        elif self._drag is not None and self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.position()
            if not self._dragging:
                if (current - self._press).manhattanLength() < QApplication.startDragDistance():
                    event.accept()
                    return
                self._dragging = True
            delta, self._drag = current - self._drag, current
            self.yaw = remainder(self.yaw + delta.x() * 0.01, 2 * pi)
            self.elevation = remainder(self.elevation + delta.y() * 0.01, 2 * pi)
            self._moving = True
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pan_button is not None and event.button() == self._pan_button:
            self._pan_drag = None
            self._pan_button = None
            self._finish_moving()
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton and self._pan_drag is None:
            position = event.position()
            clicked = (self._press is not None and not self._dragging and self._pick_allowed and
                       (position - self._press).manhattanLength() < QApplication.startDragDistance())
            self._drag = self._press = None
            self._dragging = False
            self._finish_moving()
            if (clicked and self.mesh is not None and (self._measure_mode or self.mesh.triangle_parts is not None) and
                    0 <= position.x() < self.width() and 0 <= position.y() < self.height()):
                ratio = self.devicePixelRatioF()
                width, height = max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))
                x = int(position.x() * width / max(1, self.width()))
                y = int(position.y() * height / max(1, self.height()))
                if self._renderer_button.isChecked():
                    background = self.palette().base().color()
                    rgb = (background.red(), background.green(), background.blue())
                    offset = self._pixel_offset(width, height)
                    current_key = (width, height, ratio, rgb, self.yaw, self.elevation, self.zoom, False, offset, True)
                    index = None
                    # Never use a different or stale frame to infer the visible surface.
                    if self._gpu is not None and self._frame_key == current_key:
                        try:
                            index = self._gpu.pick(self._center, self.yaw, self.elevation, self.zoom, width, height,
                                                   24 * ratio, offset, self._highlight, self._through, x, y)
                        except Exception as error:
                            self._gpu_failed(error)
                            self.update()
                else:
                    index = pick_triangle(self._triangles, self._center, self._radius, self.yaw, self.elevation,
                                          self.zoom, width, height, x, y, margin=24 * ratio,
                                          highlight=self._highlight, through=self._through,
                                          offset=self._pixel_offset(width, height))
                if self._measure_mode:
                    point = None
                    if index is not None:
                        projected, _ = screen_projection(self._triangles[index:index + 1], self._center, self._radius,
                                                         self.yaw, self.elevation, self.zoom, width, height, 24 * ratio,
                                                         offset=self._pixel_offset(width, height))
                        point = point_on_projected_triangle(self._triangles[index], projected[0],
                                                            position.x() * width / max(1, self.width()),
                                                            position.y() * height / max(1, self.height()))
                    if point is None:
                        self.point_missed.emit()
                    else:
                        self.point_picked.emit(point)
                elif index is not None:
                    self.triangle_picked.emit(index)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = max(-20., min(20., event.angleDelta().y() / 120.))
        if steps:
            self.zoom = max(0.25, min(4., self.zoom * 1.15 ** steps))
            self._moving = True
            self._settle.start()
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)
