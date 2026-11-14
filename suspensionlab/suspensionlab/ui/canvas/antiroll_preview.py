"""Условные проекции стабилизатора и стоек по рассчитанному состоянию."""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...core.antiroll import AntiRollState
from ...core.pose_view import Point, PoseView
from ...i18n import tr
from .pose_preview import PosePreview


class AntiRollPreview(QWidget):
    """Проекции Y–Z и Y–X; масштаб каждого вида одинаков для всех строк."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 250)
        self.frame: AntiRollState | None = None
        self.left_suspension: PoseView | None = None
        self.right_suspension: PoseView | None = None
        self.axis_x = 0.0
        self.axis_z = 0.0
        self.mode: Literal["front", "top"] = "front"
        self.bounds: dict[str, tuple[float, float, float, float]] = {}
        self.message = tr("analysis.preview_empty")

    def clear(self) -> None:
        self.frame = None
        self.left_suspension = self.right_suspension = None
        self.bounds = {}
        self.message = tr("analysis.preview_empty")
        self.update()

    def set_mode(self, mode: Literal["front", "top"]) -> None:
        self.mode = mode
        self.update()

    def configure(self, states: list[AntiRollState], axis_x: float, axis_z: float,
                  suspensions: list[PoseView] | None = None) -> None:
        self.axis_x, self.axis_z = axis_x, axis_z
        points: list[Point] = []
        for state in states:
            for link in (state.left, state.right):
                points.extend((link.lower_mm, link.upper_mm, (axis_x, link.upper_mm[1], axis_z)))
        for frame in suspensions or ():
            points.extend((frame.upper_front, frame.upper_rear, frame.lower_front, frame.lower_rear,
                           frame.upper_ball, frame.lower_ball))
            if frame.spring:
                points.extend(frame.spring)
            if frame.damper:
                points.extend(frame.damper)
        self.bounds = {}
        if not points:
            return
        for mode, coordinate in (("front", 2), ("top", 0)):
            ys = [point[1] for point in points]
            vertical = [point[coordinate] for point in points]
            self.bounds[mode] = (min(ys), max(ys), min(vertical), max(vertical))

    def show_frame(self, frame: AntiRollState, left: PoseView | None = None,
                   right: PoseView | None = None) -> None:
        self.frame, self.left_suspension, self.right_suspension = frame, left, right
        self.update()

    def show_missing(self) -> None:
        self.frame = None
        self.left_suspension = self.right_suspension = None
        self.message = tr("analysis.preview_no_pose")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().text().color())
        if self.frame is None or self.mode not in self.bounds:
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), self.message)
            return
        y0, y1, v0, v1 = self.bounds[self.mode]
        scale = min((self.width() - 50) / max(y1 - y0, 1), (self.height() - 90) / max(v1 - v0, 1))
        yc, vc = (y0 + y1) / 2, (v0 + v1) / 2

        def screen(point: Point) -> QPointF:
            vertical = point[2] if self.mode == "front" else point[0]
            return QPointF(self.width() / 2 - (point[1] - yc) * scale,
                           self.height() / 2 - (vertical - vc) * scale)

        for suspension in (self.left_suspension, self.right_suspension):
            if suspension is None:
                continue
            painter.setPen(QPen(QColor("#3689e6"), 2))
            for a, b in ((suspension.upper_front, suspension.upper_ball),
                         (suspension.upper_rear, suspension.upper_ball),
                         (suspension.lower_front, suspension.lower_ball),
                         (suspension.lower_rear, suspension.lower_ball),
                         (suspension.upper_ball, suspension.lower_ball)):
                painter.drawLine(screen(a), screen(b))
            if suspension.spring:
                PosePreview._draw_spring(painter, screen(suspension.spring[0]), screen(suspension.spring[1]))
            if suspension.damper:
                painter.setPen(QPen(QColor("#b670d0"), 3))
                painter.drawLine(screen(suspension.damper[0]), screen(suspension.damper[1]))
        state = self.frame
        left_pivot = (self.axis_x, state.left.upper_mm[1], self.axis_z)
        right_pivot = (self.axis_x, state.right.upper_mm[1], self.axis_z)
        painter.setPen(QPen(QColor("#8a98a8"), 4))
        painter.drawLine(screen(left_pivot), screen(right_pivot))
        painter.setPen(QPen(QColor("#dd9748"), 3))
        painter.drawLine(screen(left_pivot), screen(state.left.upper_mm))
        painter.drawLine(screen(right_pivot), screen(state.right.upper_mm))
        painter.setPen(QPen(QColor("#e35e75"), 3))
        painter.drawLine(screen(state.left.upper_mm), screen(state.left.lower_mm))
        painter.drawLine(screen(state.right.upper_mm), screen(state.right.lower_mm))
        painter.setPen(self.palette().text().color())
        title = tr("antiroll_ui.preview_front" if self.mode == "front" else "antiroll_ui.preview_top")
        painter.drawText(QRectF(8, 4, self.width() - 16, 22), int(Qt.AlignmentFlag.AlignLeft), title)
        painter.drawText(QRectF(8, self.height() - 48, self.width() - 16, 20), int(Qt.AlignmentFlag.AlignLeft),
                         tr("antiroll_ui.preview_h", left=f"{state.left_travel_mm:+.2f}",
                            right=f"{state.right_travel_mm:+.2f}"))
        painter.drawText(QRectF(8, self.height() - 27, self.width() - 16, 20), int(Qt.AlignmentFlag.AlignLeft),
                         tr("antiroll_ui.preview_force", left=f"{state.left.compression_force_n:+.1f}",
                            right=f"{state.right.compression_force_n:+.1f}"))
