"""Выбор базовой плоскости отдельного эскиза в пространственном виде."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..model.sketch_plane_view import FAR, NEAR, PLANES, Plane, pick_plane, plane_point, project

_COLORS = {"XY": "#3b82f6", "XZ": "#22a06b", "YZ": "#e59a27"}


class PlaneView(QWidget):
    planeSelected = Signal(str)

    def __init__(self, plane: Plane, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 280)
        self.setMouseTracking(True)
        self.setToolTip("Левая кнопка: выбрать плоскость. Правая кнопка и перетаскивание: вращать вид.")
        self.plane: Plane = plane
        self.yaw, self.pitch = 45., 35.
        self.hover: Plane | None = None
        self._drag: QPointF | None = None

    def set_plane(self, plane: Plane) -> None:
        self.plane = plane
        self.update()

    def _scale(self) -> float:
        return min(self.width(), self.height()) * 0.29

    def to_screen(self, point: tuple[float, float, float]) -> QPointF:
        x, y, _ = project(point, self.yaw, self.pitch)
        return QPointF(self.width() / 2 + x * self._scale(), self.height() / 2 - y * self._scale())

    def plane_at(self, pos: QPointF) -> Plane | None:
        x = (pos.x() - self.width() / 2) / self._scale()
        y = -(pos.y() - self.height() / 2) / self._scale()
        return pick_plane(x, y, self.yaw, self.pitch)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f7f9fc"))
        def depth(plane: Plane) -> float:
            return project(plane_point(plane, (NEAR + FAR) / 2, (NEAR + FAR) / 2), self.yaw, self.pitch)[2]
        # Back to front; picking uses the actual ray-plane intersection, not paint order.
        for plane in sorted(PLANES, key=depth):
            polygon = QPolygonF([self.to_screen(plane_point(plane, u, v)) for u, v in
                                 ((NEAR, NEAR), (FAR, NEAR), (FAR, FAR), (NEAR, FAR))])
            color = QColor(_COLORS[plane])
            color.setAlpha(195 if plane == self.plane else 145 if plane == self.hover else 90)
            painter.setBrush(color)
            painter.setPen(QPen(QColor(_COLORS[plane]), 3 if plane == self.plane else 1.5))
            painter.drawPolygon(polygon)
            painter.setPen(QPen(QColor("#15243a"), 1))
            painter.drawText(self.to_screen(plane_point(plane, 0.72, 0.72)), plane)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for axis, axis_color, label in ((0, "#d94b4b", "X"), (1, "#2e9c63", "Y"), (2, "#2876cc", "Z")):
            start, end = [0., 0., 0.], [0., 0., 0.]
            start[axis], end[axis] = -1.35, 1.5
            painter.setPen(QPen(QColor(axis_color), 2))
            painter.drawLine(self.to_screen((start[0], start[1], start[2])), self.to_screen((end[0], end[1], end[2])))
            painter.drawText(self.to_screen((end[0], end[1], end[2])) + QPointF(4, -4), "+" + label)
        painter.setPen(QColor("#15243a"))
        painter.drawText(self.to_screen((0., 0., 0.)) + QPointF(5, 14), "0")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._drag = event.position()
        elif event.button() == Qt.MouseButton.LeftButton:
            plane = self.plane_at(event.position())
            if plane is not None:
                self.planeSelected.emit(plane)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is not None:
            delta = event.position() - self._drag
            self._drag = event.position()
            self.yaw = (self.yaw + delta.x() * 0.5) % 360
            self.pitch = max(-80., min(80., self.pitch + delta.y() * 0.5))
            self.hover = None
        else:
            self.hover = self.plane_at(event.position())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._drag = None
        event.accept()


class SketchPlaneDialog(QDialog):
    def __init__(self, plane: Plane, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Выбор плоскости эскиза в 3D")
        self.resize(620, 520)
        layout = QVBoxLayout(self)
        notice = QLabel("Выберите цветную плоскость мышью или кнопкой. Правая кнопка мыши — вращение вида. "
                        "Показаны условные участки базовых плоскостей через начало координат; "
                        "смещение задаётся отдельно в редакторе. Это не выбор грани детали.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.view = PlaneView(plane, self)
        self.view.planeSelected.connect(self._select)
        layout.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.buttons: dict[Plane, QPushButton] = {}
        for name in PLANES:
            button = QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, chosen=name: self._select(chosen))
            self.buttons[name] = button
            row.addWidget(button)
        layout.addLayout(row)
        self.selected_label = QLabel()
        layout.addWidget(self.selected_label)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("Выбрать плоскость")
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
        self._select(plane)

    def _select(self, plane: Plane) -> None:
        if plane not in PLANES:
            return
        self.view.set_plane(plane)
        for name, button in self.buttons.items():
            button.setChecked(name == plane)
        normal = {"XY": "Z", "XZ": "Y", "YZ": "X"}[plane]
        self.selected_label.setText(f"Выбрана плоскость {plane}; смещение и выдавливание — вдоль оси {normal}.")

    @property
    def selected_plane(self) -> Plane:
        return self.view.plane
