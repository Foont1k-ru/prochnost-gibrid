"""График уже вычисленных дискретных результатов, без пересчёта подвески."""
from __future__ import annotations

from math import isfinite

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...core.sweep_plot import PLOT_METRICS, PlotPoint, plot_segments
from ...i18n import tr


class SweepPlot(QWidget):
    rowSelected = Signal(int)
    selectionTextChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, metrics: tuple[str, ...] = PLOT_METRICS,
                 label_prefix: str = "analysis.column", x_label: str = "analysis.column.travel",
                 empty_text: str = "analysis.plot_empty", zero_reference_metrics: tuple[str, ...] = ()) -> None:
        super().__init__(parent)
        if not metrics:
            raise ValueError("Графику нужна хотя бы одна величина")
        self._metrics, self._label_prefix = metrics, label_prefix
        self._x_label, self._empty_text = x_label, empty_text
        self._zero_reference_metrics = frozenset(zero_reference_metrics)
        self.setMinimumSize(300, 230)
        self.points: tuple[PlotPoint, ...] = ()
        self._metric = 0
        self.row = -1

    def set_points(self, points: tuple[PlotPoint, ...]) -> None:
        if any(len(point.values) != len(self._metrics) for point in points):
            raise ValueError("Число величин в точке не совпадает с настройкой графика")
        self.points = points
        self.row = -1
        self._selection_text()
        self.update()

    def set_metric(self, metric: int) -> None:
        if 0 <= metric < len(self._metrics):
            self._metric = metric
            self._selection_text()
            self.update()

    def set_row(self, row: int) -> None:
        self.row = row
        self._selection_text()
        self.update()

    def _selection_text(self) -> None:
        if not 0 <= self.row < len(self.points):
            self.selectionTextChanged.emit(tr("analysis.plot_no_selection"))
            return
        point = self.points[self.row]
        value = point.values[self._metric]
        text = f"{value:.6g}" if value is not None and isfinite(value) else tr("analysis.plot_value_missing")
        warning = tr("analysis.plot_conflict") if point.conflict else tr("analysis.plot_check_state")
        self.selectionTextChanged.emit(tr("analysis.plot_selection", travel=f"{point.travel_mm:+.6g}",
                                          value=text, warning=warning))

    def _geometry(self) -> tuple[QRectF, float, float, float, float] | None:
        valid = [(p.travel_mm, p.values[self._metric]) for p in self.points
                 if isfinite(p.travel_mm) and abs(p.travel_mm) < 1e100
                 and (value := p.values[self._metric]) is not None
                 and isfinite(value) and abs(value) < 1e100]
        if not valid:
            return None
        xs = [p.travel_mm for p in self.points if isfinite(p.travel_mm) and abs(p.travel_mm) < 1e100]
        ys = [float(y) for _, y in valid if y is not None]
        if self._metrics[self._metric] in self._zero_reference_metrics:
            ys.append(0.0)
        if not xs or not ys:
            return None
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        xpad = (xmax - xmin) * 0.04 if xmin != xmax else max(1.0, abs(xmin) * 0.05)
        ypad = (ymax - ymin) * 0.08 if ymin != ymax else max(0.1, abs(ymin) * 0.05)
        return QRectF(72, 35, max(1, self.width() - 90), max(1, self.height() - 90)), xmin - xpad, xmax + xpad, ymin - ypad, ymax + ypad

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
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), tr(self._empty_text))
            return
        rect, xmin, xmax, ymin, ymax = geometry
        painter.drawText(QRectF(6, 5, self.width() - 12, 24), int(Qt.AlignmentFlag.AlignLeft),
                         tr(f"{self._label_prefix}.{self._metrics[self._metric]}"))
        painter.drawRect(rect)
        for t in (0.0, 0.5, 1.0):
            x, y = xmin + (xmax - xmin) * t, ymin + (ymax - ymin) * t
            painter.drawText(QRectF(rect.left() + rect.width() * t - 34, rect.bottom() + 5, 68, 18),
                             int(Qt.AlignmentFlag.AlignCenter), f"{x:.4g}")
            painter.drawText(QRectF(0, rect.bottom() - rect.height() * t - 9, 66, 18),
                             int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{y:.4g}")
        painter.drawText(QRectF(rect.left(), self.height() - 22, rect.width(), 18),
                         int(Qt.AlignmentFlag.AlignCenter), tr(self._x_label))
        if self._metrics[self._metric] in self._zero_reference_metrics:
            y_zero = self._screen(xmin, 0.0, geometry).y()
            painter.setPen(QPen(QColor("#969696"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(rect.left(), y_zero), QPointF(rect.right(), y_zero))
        if (0 <= self.row < len(self.points) and isfinite(self.points[self.row].travel_mm)
                and abs(self.points[self.row].travel_mm) < 1e100):
            selected_x = self._screen(self.points[self.row].travel_mm, ymin, geometry).x()
            painter.setPen(QPen(QColor("#969696"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(selected_x, rect.top()), QPointF(selected_x, rect.bottom()))
        painter.setPen(QPen(QColor("#398bd1"), 2))
        for a, b in plot_segments(self.points, self._metric, len(self._metrics)):
            first, second = self.points[a], self.points[b]
            v1, v2 = first.values[self._metric], second.values[self._metric]
            if (v1 is not None and v2 is not None and abs(v1) < 1e100 and abs(v2) < 1e100
                    and abs(first.travel_mm) < 1e100 and abs(second.travel_mm) < 1e100):
                painter.drawLine(self._screen(first.travel_mm, v1, geometry), self._screen(second.travel_mm, v2, geometry))
        for i, point in enumerate(self.points):
            value = point.values[self._metric]
            if (value is None or not isfinite(value) or abs(value) >= 1e100
                    or not isfinite(point.travel_mm) or abs(point.travel_mm) >= 1e100):
                continue
            center = self._screen(point.travel_mm, value, geometry)
            color = QColor("#cf534d") if point.conflict else QColor("#398bd1")
            painter.setPen(QPen(color, 2))
            if point.conflict:
                painter.drawLine(center + QPointF(-4, -4), center + QPointF(4, 4))
                painter.drawLine(center + QPointF(-4, 4), center + QPointF(4, -4))
            else:
                painter.setBrush(color)
                painter.drawEllipse(center, 3 if i != self.row else 5, 3 if i != self.row else 5)
                painter.setBrush(Qt.BrushStyle.NoBrush)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        geometry = self._geometry()
        if event.button() != Qt.MouseButton.LeftButton or geometry is None or not geometry[0].contains(event.position()):
            return
        rect, xmin, xmax, _ymin, _ymax = geometry
        x = xmin + (event.position().x() - rect.left()) / rect.width() * (xmax - xmin)
        candidates = [i for i, point in enumerate(self.points) if isfinite(point.travel_mm) and abs(point.travel_mm) < 1e100]
        if candidates:
            self.rowSelected.emit(min(candidates, key=lambda i: abs(self.points[i].travel_mm - x)))
