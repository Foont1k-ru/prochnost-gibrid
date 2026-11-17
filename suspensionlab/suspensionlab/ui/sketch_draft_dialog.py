"""Пробный изолированный плоский эскиз; намеренно без записи в проект."""

from __future__ import annotations

from math import floor
from typing import cast

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..model.sketch_draft import Kind, Point, SketchDraft, make_entity


class SketchCanvas(QWidget):
    message = Signal(str)
    position = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(450, 360)
        self.setMouseTracking(True)
        self.draft = SketchDraft()
        self.kind: Kind = "line"
        self.pending: Point | None = None
        self.hover: Point | None = None
        self.snap = True
        self.grid = 10.0
        self.scale = 2.0
        self.offset = QPointF(0, 0)
        self._pan: QPointF | None = None
        self.plane_locked = False

    def to_screen(self, point: Point) -> QPointF:
        return QPointF(self.width() / 2 + self.offset.x() + point[0] * self.scale,
                       self.height() / 2 + self.offset.y() - point[1] * self.scale)

    def to_world(self, pos: QPointF, *, snap: bool = True) -> Point:
        x = (pos.x() - self.width() / 2 - self.offset.x()) / self.scale
        y = -(pos.y() - self.height() / 2 - self.offset.y()) / self.scale
        if snap and self.snap:
            x, y = round(x / self.grid) * self.grid, round(y / self.grid) * self.grid
        return x, y

    def set_kind(self, kind: Kind) -> None:
        self.kind = kind
        self.cancel()

    def cancel(self) -> None:
        self.pending = None
        self.hover = None
        self.update()
        self.message.emit("Выберите первую точку")

    def add_point(self, point: Point) -> None:
        if self.pending is None:
            # Проверяем и первую точку, даже если она введена без второй.
            if not all(-1_000_000 <= x <= 1_000_000 for x in point):
                self.message.emit("Точка вне допустимого диапазона")
                return
            self.pending = point
            self.plane_locked = True
            self.message.emit("Выберите вторую точку" if self.kind == "line" else "Выберите точку окружности")
        else:
            try:
                self.draft.add(self.kind, self.pending, point)
            except ValueError as exc:
                self.message.emit(str(exc))
                return
            self.pending = None
            self.message.emit("Элемент добавлен; выберите первую точку")
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._pan = event.position()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.add_point(self.to_world(event.position()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan is not None:
            self.offset += event.position() - self._pan
            self._pan = event.position()
        self.hover = self.to_world(event.position())
        self.position.emit(*self.hover)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._pan = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        before = self.to_world(event.position(), snap=False)
        self.scale = min(40.0, max(0.02, self.scale * (1.2 ** (event.angleDelta().y() / 120))))
        after = self.to_screen(before)
        self.offset += event.position() - after
        self.update()
        event.accept()

    def paintEvent(self, _event: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#151e2c"))
        # Ограничиваем число линий при сильном отдалении.
        step = self.grid
        while step * self.scale < 16:
            step *= 10
        left, top = self.to_world(QPointF(0, 0), snap=False)
        right, bottom = self.to_world(QPointF(self.width(), self.height()), snap=False)
        p.setPen(QPen(QColor("#304052"), 1))
        for i in range(floor(left / step), floor(right / step) + 2):
            x = self.to_screen((i * step, 0)).x()
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        for i in range(floor(bottom / step), floor(top / step) + 2):
            y = self.to_screen((0, i * step)).y()
            p.drawLine(QPointF(0, y), QPointF(self.width(), y))
        p.setPen(QPen(QColor("#73879e"), 1))
        origin = self.to_screen((0, 0))
        p.drawLine(QPointF(origin.x(), 0), QPointF(origin.x(), self.height()))
        p.drawLine(QPointF(0, origin.y()), QPointF(self.width(), origin.y()))
        p.setPen(QPen(QColor("#6ed5f7"), 2))
        for entity in self.draft.entities:
            self._draw_entity(p, entity.kind, entity.start, entity.end)
        if self.pending is not None and self.hover is not None:
            try:
                make_entity(self.kind, self.pending, self.hover)
            except ValueError:
                pass
            else:
                p.setPen(QPen(QColor("#f7ca72"), 1, Qt.PenStyle.DashLine))
                self._draw_entity(p, self.kind, self.pending, self.hover)
        if self.hover is not None and self.snap:
            p.setPen(QPen(QColor("#f7ca72"), 1))
            p.drawEllipse(self.to_screen(self.hover), 4, 4)
        p.end()

    def _draw_entity(self, p: QPainter, kind: Kind, start: Point, end: Point) -> None:
        a, b = self.to_screen(start), self.to_screen(end)
        if kind == "line":
            p.drawLine(a, b)
        else:
            radius = make_entity(kind, start, end).size * self.scale
            p.drawEllipse(QRectF(a.x() - radius, a.y() - radius, radius * 2, radius * 2))


class SketchDraftDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._allow_close = False
        self.setWindowTitle("Пробный плоский эскиз — без сохранения")
        self.resize(1000, 700)
        layout = QVBoxLayout(self)
        notice = QLabel("ПРОБНЫЙ ЭСКИЗ: не сохраняется и не изменяет проект. При закрытии рисунок будет потерян.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        row = QHBoxLayout()
        self.plane = QComboBox()
        self.plane.addItems(["XY", "XZ", "YZ"])
        self.plane.setToolTip("Плоскость нового эскиза; переключение доступно до начала рисования")
        row.addWidget(QLabel("Плоскость:"))
        row.addWidget(self.plane)
        self.tool = QComboBox()
        self.tool.addItems(["Отрезок", "Окружность: центр и точка"])
        row.addWidget(self.tool)
        self.snap = QCheckBox("Привязка к сетке 10 мм")
        self.snap.setChecked(True)
        row.addWidget(self.snap)
        undo, redo, cancel = QPushButton("Отменить"), QPushButton("Повторить"), QPushButton("Сбросить точку (Esc)")
        for button in (undo, redo, cancel):
            row.addWidget(button)
        layout.addLayout(row)
        self.canvas = SketchCanvas(self)
        layout.addWidget(self.canvas, 1)
        bottom = QHBoxLayout()
        form = QFormLayout()
        self.u, self.v = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.u, self.v):
            spin.setRange(-1_000_000, 1_000_000)
            spin.setDecimals(3)
            spin.setSuffix(" мм")
        form.addRow("Первая ось:", self.u)
        form.addRow("Вторая ось:", self.v)
        bottom.addLayout(form)
        add = QPushButton("Ввести точку точно")
        bottom.addWidget(add)
        self.status = QLabel("Выберите первую точку. Колесо — масштаб; правая кнопка — перемещение.")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.coords = QLabel("")
        bottom.addWidget(self.coords)
        layout.addLayout(bottom)
        self.tool.currentIndexChanged.connect(lambda i: self.canvas.set_kind(cast(Kind, "line" if i == 0 else "circle")))
        self.snap.toggled.connect(self._set_snap)
        add.clicked.connect(lambda: self.canvas.add_point((self.u.value(), self.v.value())))
        cancel.clicked.connect(self.canvas.cancel)
        undo.clicked.connect(self._undo)
        redo.clicked.connect(self._redo)
        self.canvas.message.connect(self._message)
        self.canvas.position.connect(lambda x, y: self.coords.setText(f"{x:.2f}, {y:.2f} мм"))

    def _message(self, text: str) -> None:
        self.status.setText(text)
        self.plane.setEnabled(not self.canvas.plane_locked)

    def _set_snap(self, enabled: bool) -> None:
        self.canvas.snap = enabled
        self.canvas.update()

    def _undo(self) -> None:
        self.canvas.cancel()
        self.canvas.draft.undo()
        self._message("Отмена")
        self.canvas.update()

    def _redo(self) -> None:
        self.canvas.cancel()
        self.canvas.draft.redo()
        self._message("Повтор")
        self.canvas.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.canvas.cancel()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _confirm_close(self) -> bool:
        if self._allow_close or not (self.canvas.draft.entities or self.canvas.pending is not None):
            return True
        answer = QMessageBox.question(
            self, "Закрыть эскиз?", "Эскиз нельзя сохранить; весь рисунок будет потерян. Закрыть?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def reject(self) -> None:
        if self._confirm_close():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_close():
            event.ignore()
            return
        self._allow_close = True
        try:
            super().closeEvent(event)
        finally:
            self._allow_close = False
