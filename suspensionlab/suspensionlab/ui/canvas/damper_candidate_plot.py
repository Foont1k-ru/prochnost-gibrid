"""Дискретный график сравнения: значения, упоры и заданный запас."""
from __future__ import annotations

from math import isfinite

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...core.damper_range import CandidateComparison
from ...i18n import tr


class DamperCandidatePlot(QWidget):
    """Точки не соединяются: промежуточная геометрия не вычислена."""

    rowSelected = Signal(int)
    _COLORS = {"clear": "#398bd1", "reserve_short": "#d78b18", "stop": "#d94b46"}

    def __init__(self, comparison: CandidateComparison, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.comparison = comparison
        self.row = -1
        self.setMinimumSize(300, 230)

    def set_row(self, row: int) -> None:
        self.row = row
        self.update()

    def _geometry(self) -> tuple[QRectF, float, float, float, float] | None:
        points = self.comparison.points
        xs = [p.travel_mm for p in points if isfinite(p.travel_mm) and abs(p.travel_mm) < 1e100]
        ys = [p.length_mm for p in points if p.length_mm is not None and isfinite(p.length_mm)
              and abs(p.length_mm) < 1e100]
        limits, reserve = self.comparison.limits, self.comparison.reserve_mm
        references = (limits.compressed_mm, limits.extended_mm,
                      limits.compressed_mm + reserve, limits.extended_mm - reserve)
        if not xs or not ys or any(not isfinite(v) or abs(v) >= 1e100 for v in references):
            return None
        ys.extend(references)
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        xpad = (xmax - xmin) * .04 if xmin != xmax else max(1., abs(xmin) * .05)
        ypad = (ymax - ymin) * .08 if ymin != ymax else max(.1, abs(ymin) * .05)
        return (QRectF(72, 24, max(1, self.width() - 90), max(1, self.height() - 79)),
                xmin - xpad, xmax + xpad, ymin - ypad, ymax + ypad)

    @staticmethod
    def _screen(x: float, y: float, geometry: tuple[QRectF, float, float, float, float]) -> QPointF:
        rect, xmin, xmax, ymin, ymax = geometry
        return QPointF(rect.left() + (x - xmin) / (xmax - xmin) * rect.width(),
                       rect.bottom() - (y - ymin) / (ymax - ymin) * rect.height())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().text().color())
        geometry = self._geometry()
        if geometry is None:
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                             tr("damper_candidate.plot.empty"))
            return
        rect, xmin, xmax, ymin, ymax = geometry
        painter.drawText(QRectF(6, 0, self.width() - 12, 22), int(Qt.AlignmentFlag.AlignLeft),
                         tr("damper_candidate.plot.y_axis"))
        painter.drawRect(rect)
        for t in (0., .5, 1.):
            painter.drawText(QRectF(rect.left() + rect.width() * t - 34, rect.bottom() + 5, 68, 18),
                             int(Qt.AlignmentFlag.AlignCenter), f"{xmin + (xmax - xmin) * t:.4g}")
            painter.drawText(QRectF(0, rect.bottom() - rect.height() * t - 9, 66, 18),
                             int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{ymin + (ymax - ymin) * t:.4g}")
        painter.drawText(QRectF(rect.left(), self.height() - 20, rect.width(), 18),
                         int(Qt.AlignmentFlag.AlignCenter), tr("damper_candidate.plot.x_axis"))
        limits, reserve = self.comparison.limits, self.comparison.reserve_mm
        refs = [(limits.compressed_mm, "#d94b46", Qt.PenStyle.DashLine),
                (limits.extended_mm, "#d94b46", Qt.PenStyle.DashLine)]
        if reserve > 0:
            refs.extend(((limits.compressed_mm + reserve, "#d78b18", Qt.PenStyle.DotLine),
                         (limits.extended_mm - reserve, "#d78b18", Qt.PenStyle.DotLine)))
        for value, reference_color, style in refs:
            painter.setPen(QPen(QColor(reference_color), 1.5, style))
            y = self._screen(xmin, value, geometry).y()
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for i, point in enumerate(self.comparison.points):
            if not isfinite(point.travel_mm) or abs(point.travel_mm) >= 1e100:
                continue
            if point.length_mm is None:
                # Пропуск привязан к оси X, а не к вымышленной длине.
                x = self._screen(point.travel_mm, ymin, geometry).x()
                painter.setPen(QPen(QColor("#888888"), 2))
                painter.drawLine(QPointF(x, rect.bottom() - 6), QPointF(x, rect.bottom() + 1))
                if i == self.row:
                    painter.setPen(QPen(self.palette().text().color(), 1.5))
                    painter.drawRect(QRectF(x - 5, rect.bottom() - 11, 10, 10))
                continue
            if not isfinite(point.length_mm) or abs(point.length_mm) >= 1e100:
                continue
            center = self._screen(point.travel_mm, point.length_mm, geometry)
            color = QColor(self._COLORS[point.status])
            painter.setPen(QPen(color, 2))
            if point.status == "stop":
                painter.drawLine(center + QPointF(-4, -4), center + QPointF(4, 4))
                painter.drawLine(center + QPointF(-4, 4), center + QPointF(4, -4))
            elif point.status == "reserve_short":
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(center.x() - 4, center.y() - 4, 8, 8))
            else:
                painter.setBrush(color)
                painter.drawEllipse(center, 3, 3)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            if i == self.row:
                painter.setPen(QPen(self.palette().text().color(), 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(center, 7, 7)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        geometry = self._geometry()
        if event.button() != Qt.MouseButton.LeftButton or geometry is None or not geometry[0].contains(event.position()):
            return
        candidates = [(abs(self._screen(p.travel_mm, geometry[3], geometry).x() - event.position().x()), i)
                      for i, p in enumerate(self.comparison.points)
                      if isfinite(p.travel_mm) and abs(p.travel_mm) < 1e100]
        if candidates:
            distance, row = min(candidates)
            if distance <= 12:
                self.rowSelected.emit(row)
                event.accept()
