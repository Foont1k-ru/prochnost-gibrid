"""Изолированный плоский эскиз, отдельный от проекта подвески."""

from __future__ import annotations

from math import atan2, degrees, floor, hypot
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..model.sketch_construction import tangent_circles, trim_entity
from ..model.sketch_contours import ContourIssue, check_contours
from ..model.sketch_draft import (
    LIMIT_MM,
    Entity,
    Kind,
    Point,
    SketchDraft,
    arc_end,
    drawing_bounds,
    make_entity,
    rectangle_entities,
)
from ..model.sketch_dxf import SketchDxfError, write_new_dxf
from ..model.sketch_io import SUFFIX, SketchDocument, SketchIOError, read_sketch, write_new_sketch

Tool = Literal["line", "circle", "rectangle", "chain", "measure", "arc", "trim", "tangent2", "tangent3"]


def _distance_to_entity(point: Point, entity: Entity) -> float:
    x, y = point
    ax, ay = entity.start
    bx, by = entity.end
    if entity.kind in ("circle", "arc"):
        radial = abs(hypot(x - ax, y - ay) - entity.size)
        if entity.kind == "circle":
            return radial
        assert entity.sweep_deg is not None
        start_angle = degrees(atan2(by - ay, bx - ax))
        angle = degrees(atan2(y - ay, x - ax))
        distance_angle = (angle - start_angle) % 360 if entity.sweep_deg > 0 else (start_angle - angle) % 360
        if distance_angle <= abs(entity.sweep_deg):
            return radial
        finish = arc_end(entity)
        return min(hypot(x - bx, y - by), hypot(x - finish[0], y - finish[1]))
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
    return hypot(x - (ax + t * dx), y - (ay + t * dy))


class SketchCanvas(QWidget):
    message = Signal(str)
    position = Signal(float, float)
    changed = Signal()
    selectionChanged = Signal()
    trimRequested = Signal(int, object)
    tangentRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(450, 320)
        self.setMouseTracking(True)
        self.draft = SketchDraft()
        self.kind: Tool | None = "line"  # None = selection
        self.pending: Point | None = None
        self.measure_start: Point | None = None
        self.hover: Point | None = None
        self.snap = True
        self.snap_points = True
        self.snap_label = ""
        self.grid = 10.0
        self.scale = 2.0
        self.offset = QPointF(0, 0)
        self._pan: QPointF | None = None
        self.plane_locked = False
        self.selected: int | None = None
        self.construction_indices: list[int] = []
        self.arc_sweep = 90.0
        self.diagnostic_indices: set[int] = set()
        self.diagnostic_points: tuple[Point, ...] = ()
        self.diagnostic_snapshot: tuple[Entity, ...] | None = None

    def to_screen(self, point: Point) -> QPointF:
        return QPointF(self.width() / 2 + self.offset.x() + point[0] * self.scale,
                       self.height() / 2 + self.offset.y() - point[1] * self.scale)

    def to_world(self, pos: QPointF, *, snap: bool = True) -> Point:
        x = (pos.x() - self.width() / 2 - self.offset.x()) / self.scale
        y = -(pos.y() - self.height() / 2 - self.offset.y()) / self.scale
        if snap and self.snap:
            x, y = round(x / self.grid) * self.grid, round(y / self.grid) * self.grid
        return x, y

    def mouse_point(self, pos: QPointF) -> Point:
        raw = self.to_world(pos, snap=False)
        self.snap_label = ""
        if self.snap_points:
            best: Point | None = None
            distance = 10.0 / self.scale
            for entity in self.draft.entities:
                points: list[tuple[Point, str]] = [(entity.start, "точка"), (entity.end, "точка")]
                if entity.kind == "arc":
                    points.append((arc_end(entity), "конец дуги"))
                if entity.kind == "line":
                    points.append((((entity.start[0] + entity.end[0]) / 2,
                                    (entity.start[1] + entity.end[1]) / 2), "середина"))
                for point, label in points:
                    d = hypot(raw[0] - point[0], raw[1] - point[1])
                    if d < distance:
                        best, distance = point, d
                        self.snap_label = label
            if best is not None:
                return best
        if self.snap:
            self.snap_label = "сетка"
            return self.to_world(pos)
        return raw

    def set_kind(self, kind: Tool | None) -> None:
        self.kind = kind
        self.cancel()
        self.selected = None
        self.selectionChanged.emit()
        self.update()

    def cancel(self) -> None:
        self.pending = None
        self.measure_start = None
        self.construction_indices.clear()
        self.hover = None
        self.update()
        self.message.emit("Выберите элемент" if self.kind is None else "Выберите первую точку")
        self.changed.emit()

    def add_point(self, point: Point) -> None:
        if self.kind is None or self.kind in ("trim", "tangent2", "tangent3"):
            return
        if self.kind == "measure":
            if not all(-LIMIT_MM <= value <= LIMIT_MM for value in point):
                self.message.emit("Точка вне допустимого диапазона")
                return
            if self.measure_start is None:
                self.measure_start = point
                self.message.emit("Измерение: выберите вторую точку")
            else:
                dx = point[0] - self.measure_start[0]
                dy = point[1] - self.measure_start[1]
                self.measure_start = None
                self.message.emit(f"Расстояние: {hypot(dx, dy):.3f} мм; Δ1: {dx:.3f} мм; Δ2: {dy:.3f} мм")
            self.update()
            return
        if self.pending is None:
            if not all(-LIMIT_MM <= x <= LIMIT_MM for x in point):
                self.message.emit("Точка вне допустимого диапазона")
                return
            self.pending = point
            self.plane_locked = True
            prompt = {"line": "Выберите вторую точку", "chain": "Выберите следующую точку цепочки",
                      "rectangle": "Выберите противоположный угол", "circle": "Выберите точку окружности",
                      "arc": "Выберите начальную точку дуги"}
            self.message.emit(prompt[self.kind])
        else:
            try:
                if self.kind == "rectangle":
                    self.draft.add_rectangle(self.pending, point)
                elif self.kind == "arc":
                    self.draft.add_arc(self.pending, point, self.arc_sweep)
                else:
                    self.draft.add("circle" if self.kind == "circle" else "line", self.pending, point)
            except ValueError as exc:
                self.message.emit(str(exc))
                return
            if self.kind == "chain":
                self.pending = point
                self.message.emit("Отрезок добавлен; следующая точка или Esc для завершения цепочки")
            else:
                self.pending = None
                self.message.emit("Элемент добавлен; выберите первую точку")
        self.changed.emit()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._pan = event.position()
        elif event.button() == Qt.MouseButton.LeftButton:
            if self.kind is None:
                point = self.to_world(event.position(), snap=False)
                candidates = [(_distance_to_entity(point, e), i) for i, e in enumerate(self.draft.entities)]
                best = min(candidates, default=(float("inf"), -1))
                self.selected = best[1] if best[0] <= 8.0 / self.scale else None
                self.selectionChanged.emit()
                self.update()
            elif self.kind in ("trim", "tangent2", "tangent3"):
                point = self.to_world(event.position(), snap=False)
                candidates = [(_distance_to_entity(point, e), i) for i, e in enumerate(self.draft.entities)
                              if e.kind == "line" or (self.kind == "trim" and e.kind in ("circle", "arc"))]
                best = min(candidates, default=(float("inf"), -1))
                if best[0] > 8.0 / self.scale:
                    self.message.emit("Выберите отрезок, окружность или дугу" if self.kind == "trim" else "Выберите отрезок рядом с курсором")
                elif self.kind == "trim":
                    self.trimRequested.emit(best[1], point)
                elif best[1] in self.construction_indices:
                    self.message.emit("Выберите другой отрезок")
                else:
                    self.construction_indices.append(best[1])
                    needed = 2 if self.kind == "tangent2" else 3
                    self.message.emit(f"Выбрано отрезков: {len(self.construction_indices)} из {needed}; Esc — сброс")
                    self.update()
                    if len(self.construction_indices) == needed:
                        self.tangentRequested.emit(tuple(self.construction_indices))
                        self.construction_indices.clear()
                        self.update()
            else:
                self.add_point(self.mouse_point(event.position()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan is not None:
            self.offset += event.position() - self._pan
            self._pan = event.position()
        if self.kind is None or self.kind in ("trim", "tangent2", "tangent3"):
            self.snap_label = ""
            self.hover = self.to_world(event.position(), snap=False)
        else:
            self.hover = self.mouse_point(event.position())
        self.position.emit(*self.hover)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._pan = None

    def fit_view(self) -> bool:
        bounds = drawing_bounds(tuple(self.draft.entities))
        if bounds is None:
            self.message.emit("Нет элементов для показа")
            return False
        left, bottom, right, top = bounds
        width, height = max(right - left, 1e-9), max(top - bottom, 1e-9)
        self.scale = min(40.0, max(0.00001, min(max(1, self.width() - 80) / width,
                                                    max(1, self.height() - 80) / height)))
        self.offset = QPointF(-(left + right) / 2 * self.scale, (bottom + top) / 2 * self.scale)
        self.update()
        return True

    def wheelEvent(self, event: QWheelEvent) -> None:
        before = self.to_world(event.position(), snap=False)
        steps = max(-20.0, min(20.0, event.angleDelta().y() / 120))
        self.scale = min(40.0, max(0.00001, self.scale * (1.2 ** steps)))
        after = self.to_screen(before)
        self.offset += event.position() - after
        self.update()
        event.accept()

    def paintEvent(self, _event: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#151e2c"))
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
        for i, entity in enumerate(self.draft.entities):
            selected = i == self.selected or i in self.construction_indices
            color = "#f7ca72" if selected else ("#ff6e6e" if i in self.diagnostic_indices else "#6ed5f7")
            p.setPen(QPen(QColor(color), 3 if selected or i in self.diagnostic_indices else 2))
            self._draw_entity(p, entity.kind, entity.start, entity.end, entity.sweep_deg)
        p.setPen(QPen(QColor("#ff6e6e"), 2))
        for point in self.diagnostic_points:
            p.drawEllipse(self.to_screen(point), 5, 5)
        if self.kind == "measure" and self.measure_start is not None and self.hover is not None:
            p.setPen(QPen(QColor("#f7ca72"), 1, Qt.PenStyle.DashLine))
            p.drawLine(self.to_screen(self.measure_start), self.to_screen(self.hover))
            p.drawEllipse(self.to_screen(self.measure_start), 4, 4)
        if self.kind in ("line", "chain", "circle", "arc", "rectangle") and self.pending is not None and self.hover is not None:
            try:
                if self.kind == "rectangle":
                    preview = rectangle_entities(self.pending, self.hover)
                else:
                    shape: Kind = "arc" if self.kind == "arc" else ("circle" if self.kind == "circle" else "line")
                    preview = (make_entity(shape, self.pending, self.hover,
                                           self.arc_sweep if self.kind == "arc" else None),)
            except ValueError:
                pass
            else:
                p.setPen(QPen(QColor("#f7ca72"), 1, Qt.PenStyle.DashLine))
                for item in preview:
                    self._draw_entity(p, item.kind, item.start, item.end, item.sweep_deg)
        if self.hover is not None and self.snap_label and self.kind is not None:
            p.setPen(QPen(QColor("#f7ca72"), 1))
            p.drawEllipse(self.to_screen(self.hover), 4, 4)
        p.end()

    def _draw_entity(self, p: QPainter, kind: Kind, start: Point, end: Point, sweep: float | None = None) -> None:
        a, b = self.to_screen(start), self.to_screen(end)
        if kind == "line":
            p.drawLine(a, b)
        else:
            radius = make_entity(kind, start, end, sweep).size * self.scale
            rect = QRectF(a.x() - radius, a.y() - radius, radius * 2, radius * 2)
            if kind == "arc":
                assert sweep is not None
                angle = degrees(atan2(end[1] - start[1], end[0] - start[0]))
                p.drawArc(rect, round(angle * 16), round(sweep * 16))
            else:
                p.drawEllipse(rect)


class TangentPreview(QWidget):
    """Изолированный неизменяемый предпросмотр вариантов касания."""

    def __init__(self, lines: tuple[Entity, ...], circles: tuple[Entity, ...], parent: QWidget) -> None:
        super().__init__(parent)
        self.lines, self.circles = lines, circles
        self.index = 0
        self.setMinimumSize(440, 300)

    def set_index(self, index: int) -> None:
        self.index = index
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#151e2c"))
        circle = self.circles[self.index]
        bounds = drawing_bounds((*self.lines, circle))
        assert bounds is not None
        left, bottom, right, top = bounds
        scale = min(max(1, self.width() - 60) / max(right - left, 1e-9),
                    max(1, self.height() - 60) / max(top - bottom, 1e-9), 200.0)
        cx, cy = (left + right) / 2, (bottom + top) / 2

        def screen(point: Point) -> QPointF:
            return QPointF(self.width() / 2 + (point[0] - cx) * scale,
                           self.height() / 2 - (point[1] - cy) * scale)

        painter.setPen(QPen(QColor("#6ed5f7"), 2))
        for line in self.lines:
            painter.drawLine(screen(line.start), screen(line.end))
        painter.setPen(QPen(QColor("#f7ca72"), 2))
        center = screen(circle.start)
        radius = circle.size * scale
        painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius))
        painter.setPen(QPen(QColor("#ff6e6e"), 2))
        for line in self.lines:
            dx, dy = line.end[0] - line.start[0], line.end[1] - line.start[1]
            t = ((circle.start[0] - line.start[0]) * dx + (circle.start[1] - line.start[1]) * dy) / line.size ** 2
            foot = (line.start[0] + t * dx, line.start[1] + t * dy)
            painter.drawEllipse(screen(foot), 4, 4)
        painter.end()


class TangentChoiceDialog(QDialog):
    def __init__(self, lines: tuple[Entity, ...], circles: tuple[Entity, ...], parent: QWidget) -> None:
        super().__init__(parent)
        self.circles = circles
        self.setWindowTitle("Выбор касательной окружности")
        layout = QVBoxLayout(self)
        label = QLabel("Выберите вариант. Красные точки — касания. Связь с отрезками не сохраняется.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.choice = QComboBox()
        self.choice.addItems([f"Центр ({c.start[0]:.4f}, {c.start[1]:.4f}) мм; R {c.size:.4f} мм" for c in circles])
        layout.addWidget(self.choice)
        self.preview = TangentPreview(lines, circles, self)
        layout.addWidget(self.preview)
        self.choice.currentIndexChanged.connect(self.preview.set_index)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_circle(self) -> Entity:
        return self.circles[self.choice.currentIndex()]


class EntityEditor(QDialog):
    def __init__(self, entity: Entity, parent: QWidget) -> None:
        super().__init__(parent)
        self.entity = entity
        self.setWindowTitle("Точные параметры элемента")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.values: list[QDoubleSpinBox] = []
        labels: tuple[str, ...] = ("Начало, первая ось", "Начало, вторая ось", "Конец, первая ось", "Конец, вторая ось")
        numbers: tuple[float, ...]
        if entity.kind in ("circle", "arc"):
            labels = ("Центр, первая ось", "Центр, вторая ось", "Радиус")
            numbers = (*entity.start, entity.size)
            if entity.kind == "arc":
                assert entity.sweep_deg is not None
                labels += ("Угол дуги, градусы",)
                numbers += (entity.sweep_deg,)
        else:
            numbers = (*entity.start, *entity.end)
        for label, value in zip(labels, numbers, strict=True):
            spin = QDoubleSpinBox()
            spin.setDecimals(9)
            spin.setRange(-2_900_000, 2_900_000)
            spin.setSuffix(" мм")
            if "градусы" in label:
                spin.setRange(-359.999999, 359.999999)
                spin.setSuffix("°")
            spin.setValue(value)
            self.values.append(spin)
            form.addRow(label, spin)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_entity(self) -> Entity:
        v = [spin.value() for spin in self.values]
        start = (v[0], v[1])
        if self.entity.kind == "line":
            end = (v[2], v[3])
        else:
            if v[2] <= 0:
                raise ValueError("Радиус должен быть больше нуля")
            # Сохраняем направление исходной точки окружности.
            dx = (self.entity.end[0] - self.entity.start[0]) / self.entity.size
            dy = (self.entity.end[1] - self.entity.start[1]) / self.entity.size
            end = (start[0] + v[2] * dx, start[1] + v[2] * dy)
        return make_entity(self.entity.kind, start, end, v[3] if self.entity.kind == "arc" else None)

    def _accept_checked(self) -> None:
        try:
            self.result_entity()
        except ValueError as exc:
            QMessageBox.warning(self, "Некорректные параметры", str(exc))
            return
        self.accept()


class SketchDraftDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._allow_close = False
        self._path: Path | None = None
        self.setWindowTitle("Плоский эскиз — отдельный документ")
        self.resize(1100, 750)
        layout = QVBoxLayout(self)
        notice = QLabel("Эскиз отдельно от проекта подвески; 3D-тело и связь с рычагами пока не создаются. "
                        "Каждое сохранение — в новый .slsketch, существующие файлы не перезаписываются.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        files = QHBoxLayout()
        new, open_button, save = QPushButton("Новый"), QPushButton("Открыть…"), QPushButton("Сохранить как новый…")
        export = QPushButton("Экспорт DXF…")
        for button in (new, open_button, save, export):
            files.addWidget(button)
        self.file_label = QLabel("Новый эскиз")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        files.addWidget(self.file_label, 1)
        layout.addLayout(files)
        row = QHBoxLayout()
        self.plane = QComboBox()
        self.plane.addItems(["XY", "XZ", "YZ"])
        row.addWidget(QLabel("Плоскость:"))
        row.addWidget(self.plane)
        self.plane_offset = QDoubleSpinBox()
        self.plane_offset.setRange(-LIMIT_MM, LIMIT_MM)
        self.plane_offset.setDecimals(3)
        self.plane_offset.setSuffix(" мм")
        self.plane_offset.setToolTip("Положение по оставшейся оси: XY → Z, XZ → Y, YZ → X")
        row.addWidget(QLabel("Смещение:"))
        row.addWidget(self.plane_offset)
        self.tool = QComboBox()
        self.tool.addItems(["Отрезок", "Окружность: центр и точка", "Выбор элемента",
                            "Прямоугольник: два угла", "Цепочка отрезков", "Измерить расстояние",
                            "Дуга: центр, начало, угол", "Обрезать участок", "Окружность по 2 отрезкам",
                            "Окружность по 3 отрезкам"])
        row.addWidget(self.tool)
        self.snap = QCheckBox("Сетка")
        self.snap.setChecked(True)
        row.addWidget(self.snap)
        self.grid_step = QDoubleSpinBox()
        self.grid_step.setDecimals(3)
        self.grid_step.setRange(0.001, 100_000)
        self.grid_step.setValue(10)
        self.grid_step.setSuffix(" мм")
        row.addWidget(self.grid_step)
        self.points_snap = QCheckBox("Точки и середины")
        self.points_snap.setChecked(True)
        row.addWidget(self.points_snap)
        layout.addLayout(row)
        tools = QHBoxLayout()
        undo, redo, cancel = QPushButton("Отменить"), QPushButton("Повторить"), QPushButton("Завершить / сбросить (Esc)")
        self.edit_button, self.delete_button = QPushButton("Изменить выбранное…"), QPushButton("Удалить выбранное")
        fit = QPushButton("Показать весь эскиз")
        for button in (undo, redo, cancel, self.edit_button, self.delete_button, fit):
            tools.addWidget(button)
        layout.addLayout(tools)
        parameters = QHBoxLayout()
        parameters.addWidget(QLabel("Угол дуги (+ против часовой):"))
        self.arc_angle = QDoubleSpinBox()
        self.arc_angle.setRange(-359.999, 359.999)
        self.arc_angle.setDecimals(3)
        self.arc_angle.setValue(90)
        self.arc_angle.setSuffix("°")
        parameters.addWidget(self.arc_angle)
        parameters.addWidget(QLabel("Радиус касания к двум отрезкам:"))
        self.tangent_radius = QDoubleSpinBox()
        self.tangent_radius.setDecimals(3)
        self.tangent_radius.setRange(0.001, 1_000_000)
        self.tangent_radius.setValue(10)
        self.tangent_radius.setSuffix(" мм")
        parameters.addWidget(self.tangent_radius)
        parameters.addStretch(1)
        layout.addLayout(parameters)
        diagnostics = QHBoxLayout()
        check = QPushButton("Проверить контуры")
        diagnostics.addWidget(check)
        diagnostics.addWidget(QLabel("Допуск близости:"))
        self.contour_tolerance = QDoubleSpinBox()
        self.contour_tolerance.setDecimals(3)
        self.contour_tolerance.setRange(0.001, 1.0)
        self.contour_tolerance.setValue(0.01)
        self.contour_tolerance.setSuffix(" мм")
        self.contour_tolerance.setToolTip("Близкие концы отмечаются, но не соединяются автоматически")
        diagnostics.addWidget(self.contour_tolerance)
        diagnostics.addWidget(QLabel("Предварительная проверка; геометрия не изменяется"), 1)
        layout.addLayout(diagnostics)
        self.canvas = SketchCanvas(self)
        layout.addWidget(self.canvas, 1)
        bottom = QHBoxLayout()
        form = QFormLayout()
        self.u, self.v = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.u, self.v):
            spin.setRange(-LIMIT_MM, LIMIT_MM)
            spin.setDecimals(3)
            spin.setSuffix(" мм")
        form.addRow("Первая ось:", self.u)
        form.addRow("Вторая ось:", self.v)
        bottom.addLayout(form)
        self.add_button = QPushButton("Ввести точку точно")
        bottom.addWidget(self.add_button)
        self.status = QLabel("Колесо — масштаб; правая кнопка — перемещение. Плоскость блокируется при первой точке.")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.coords = QLabel("")
        bottom.addWidget(self.coords)
        layout.addLayout(bottom)
        self._saved = self._document()
        new.clicked.connect(self._new)
        open_button.clicked.connect(self._open)
        save.clicked.connect(self._save)
        export.clicked.connect(self._export_dxf)
        self.plane.currentIndexChanged.connect(self._reference_changed)
        self.plane_offset.valueChanged.connect(self._reference_changed)
        self.tool.currentIndexChanged.connect(self._set_tool)
        self.snap.toggled.connect(self._set_snap)
        self.points_snap.toggled.connect(self._set_points_snap)
        self.grid_step.valueChanged.connect(self._set_grid)
        self.add_button.clicked.connect(lambda: self.canvas.add_point((self.u.value(), self.v.value())))
        cancel.clicked.connect(self.canvas.cancel)
        undo.clicked.connect(self._undo)
        redo.clicked.connect(self._redo)
        fit.clicked.connect(self.canvas.fit_view)
        check.clicked.connect(self._check_contours)
        self.contour_tolerance.valueChanged.connect(self._clear_diagnostics)
        self.edit_button.clicked.connect(self._edit)
        self.delete_button.clicked.connect(self._delete)
        self.canvas.message.connect(self._message)
        self.canvas.changed.connect(self._refresh)
        self.canvas.selectionChanged.connect(self._selection_changed)
        self.canvas.trimRequested.connect(self._trim)
        self.canvas.tangentRequested.connect(self._tangent)
        self.arc_angle.valueChanged.connect(self._arc_angle_changed)
        self.canvas.position.connect(self._position)
        self._refresh()

    def _document(self) -> SketchDocument:
        return SketchDocument(self.plane.currentText(), self.plane_offset.value(), tuple(self.canvas.draft.entities))

    def _dirty(self) -> bool:
        return self._document() != self._saved or self.canvas.pending is not None

    def _refresh(self, *_args: object) -> None:
        if (self.canvas.diagnostic_snapshot is not None and
                self.canvas.diagnostic_snapshot != tuple(self.canvas.draft.entities)):
            self._clear_diagnostics()
        self.plane.setEnabled(not self.canvas.plane_locked)
        self.plane_offset.setEnabled(not self.canvas.plane_locked)
        selected = self.canvas.selected is not None
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        self.add_button.setEnabled(self.canvas.kind in ("line", "circle", "rectangle", "chain", "measure", "arc"))
        name = str(self._path) if self._path else "Новый эскиз"
        self.file_label.setText(name + (" *" if self._dirty() else ""))

    def _reference_changed(self, *_args: object) -> None:
        if self.canvas.measure_start is not None:
            self.canvas.measure_start = None
            self.canvas.update()
            self._message("Измерение сброшено: плоскость или её положение изменились")
        else:
            self._refresh()

    def _message(self, text: str) -> None:
        self.status.setText(text)
        self._refresh()

    def _position(self, x: float, y: float) -> None:
        self.coords.setText(f"{self.plane.currentText()}: {x:.3f}, {y:.3f} мм {self.canvas.snap_label}")

    def _selection_changed(self) -> None:
        index = self.canvas.selected
        if index is not None:
            entity = self.canvas.draft.entities[index]
            if entity.kind == "line":
                self._message(f"Элемент {index + 1} — отрезок: длина {entity.size:.3f} мм")
            elif entity.kind == "circle":
                self._message(f"Элемент {index + 1} — окружность: радиус {entity.size:.3f} мм; диаметр {2 * entity.size:.3f} мм")
            else:
                self._message(f"Элемент {index + 1} — дуга: радиус {entity.size:.3f} мм; угол {entity.sweep_deg:.3f}°")
        else:
            self._refresh()

    def _set_tool(self, index: int) -> None:
        kinds: tuple[Tool | None, ...] = ("line", "circle", None, "rectangle", "chain", "measure",
                                               "arc", "trim", "tangent2", "tangent3")
        self.canvas.set_kind(kinds[index])
        if kinds[index] == "trim":
            self._message("Нажмите на удаляемый участок отрезка, дуги или окружности между пересечениями")
        elif kinds[index] in ("tangent2", "tangent3"):
            self._message("Выберите мышью разные отрезки; касание строится одноразово без ограничения")

    def _arc_angle_changed(self, value: float) -> None:
        self.canvas.arc_sweep = value
        self.canvas.update()

    def _trim(self, index: int, point: Point) -> None:
        try:
            parts = trim_entity(tuple(self.canvas.draft.entities), index, point)
            self.canvas.draft.replace_with(index, parts)
        except ValueError as exc:
            self._message(str(exc))
            return
        self._message("Участок удалён; кнопка отмены вернёт его")
        self.canvas.update()

    def _tangent(self, indices: tuple[int, ...]) -> None:
        lines = tuple(self.canvas.draft.entities[index] for index in indices)
        try:
            candidates = tangent_circles(lines, self.tangent_radius.value() if len(lines) == 2 else None)
        except ValueError as exc:
            self._message(str(exc))
            return
        if not candidates:
            self._message("Нет решения на выбранных конечных отрезках; измените отрезки или радиус")
            return
        choice = TangentChoiceDialog(lines, candidates, self)
        result = choice.exec()
        entity = choice.selected_circle() if result == QDialog.DialogCode.Accepted else None
        choice.deleteLater()
        if entity is None:
            self._message("Построение отменено")
            return
        try:
            self.canvas.draft.add("circle", entity.start, entity.end)
        except ValueError as exc:
            self._message(str(exc))
            return
        self._message("Окружность добавлена; касание не связано с последующим изменением отрезков")
        self.canvas.update()

    def _set_snap(self, enabled: bool) -> None:
        self.canvas.snap = enabled
        self.canvas.update()

    def _set_points_snap(self, enabled: bool) -> None:
        self.canvas.snap_points = enabled
        self.canvas.update()

    def _set_grid(self, value: float) -> None:
        self.canvas.grid = value
        self.canvas.update()

    def _clear_diagnostics(self, *_args: object) -> None:
        self.canvas.diagnostic_snapshot = None
        self.canvas.diagnostic_indices.clear()
        self.canvas.diagnostic_points = ()
        self.canvas.update()

    @staticmethod
    def _describe_issue(issue: ContourIssue) -> str:
        elements = ", ".join(str(index + 1) for index in issue.indices)
        points = "; ".join(f"({x:.6f}, {y:.6f})" for x, y in issue.points)
        return f"• {issue.message}" + (f" — элементы {elements}" if elements else "") + (f"; точки {points}" if points else "")

    def _check_contours(self) -> None:
        if self.canvas.pending is not None:
            QMessageBox.warning(self, "Проверка контуров", "Завершите построение или нажмите Esc перед проверкой.")
            return
        try:
            report = check_contours(tuple(self.canvas.draft.entities), self.contour_tolerance.value())
        except ValueError as exc:
            self._clear_diagnostics()
            QMessageBox.warning(self, "Проверка контуров", str(exc))
            return
        self.canvas.diagnostic_snapshot = tuple(self.canvas.draft.entities)
        self.canvas.diagnostic_indices = {index for issue in report.issues for index in issue.indices}
        self.canvas.diagnostic_points = tuple(point for issue in report.issues for point in issue.points)
        self.canvas.update()
        notice = ("Предварительная проверка отрезков, окружностей и дуг не гарантирует пригодность для 3D или производства. "
                  "Разрывы не исправляются. Расхождение до 0,00000001 мм считается вычислительным шумом.")
        if report.total_issues:
            details = "\n".join(self._describe_issue(issue) for issue in report.issues[:12])
            remainder = "\nПоказаны первые 12; подсветка ограничена первыми 100 замечаниями." if report.total_issues > 12 else ""
            text = f"Найдено замечаний: {report.total_issues}. Проблемные элементы выделены красным.\n\n{details}{remainder}\n\n{notice}"
            self._message(f"Проверка: замечаний {report.total_issues}")
        else:
            text = f"Замечаний не найдено. Замкнутых контуров по этой проверке: {report.closed_loops}.\n\n{notice}"
            self._message(f"Проверка: замечаний нет, контуров {report.closed_loops}")
        QMessageBox.information(self, "Проверка контуров", text)

    def _undo(self) -> None:
        if self.canvas.pending is not None or self.canvas.construction_indices:
            self.canvas.cancel()
            return
        self.canvas.draft.undo()
        self.canvas.selected = None
        self._message("Отмена")
        self.canvas.update()

    def _redo(self) -> None:
        if self.canvas.pending is not None or self.canvas.construction_indices:
            self.canvas.cancel()
            return
        self.canvas.draft.redo()
        self.canvas.selected = None
        self._message("Повтор")
        self.canvas.update()

    def _edit(self) -> None:
        index = self.canvas.selected
        if index is None:
            return
        editor = EntityEditor(self.canvas.draft.entities[index], self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            entity = editor.result_entity()
            self.canvas.draft.replace(index, entity.kind, entity.start, entity.end, entity.sweep_deg)
            self._message("Элемент изменён")
            self.canvas.update()

    def _delete(self) -> None:
        index = self.canvas.selected
        if index is None:
            return
        self.canvas.draft.delete(index)
        self.canvas.selected = None
        self._message("Элемент удалён; его можно вернуть кнопкой «Отменить»")
        self.canvas.update()

    def _save(self) -> bool:
        if self.canvas.pending is not None:
            QMessageBox.warning(self, "Незавершённый элемент", "Завершите действие или нажмите Esc, затем сохраните эскиз.")
            return False
        suggested = str(self._path.with_name(self._path.stem + "-новый" + SUFFIX)) if self._path else "эскиз.slsketch"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить новый эскиз", suggested,
                                              "Эскиз Подвеска.Про (*.slsketch)",
                                              options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return False
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(SUFFIX)
        try:
            doc = self._document()
            write_new_sketch(target, doc)
        except (SketchIOError, OSError) as exc:
            QMessageBox.warning(self, "Сохранение не выполнено", f"{exc}\nВыберите новое имя файла.")
            return False
        self._path, self._saved = target, doc
        self._message("Эскиз сохранён в новый файл")
        return True

    def _export_dxf(self) -> bool:
        if self.canvas.pending is not None:
            QMessageBox.warning(self, "Экспорт DXF", "Завершите действие или нажмите Esc перед экспортом.")
            return False
        if not self.canvas.draft.entities:
            QMessageBox.warning(self, "Экспорт DXF", "Эскиз пуст.")
            return False
        answer = QMessageBox.question(
            self, "Экспорт DXF",
            f"Экспортировать плоскую копию в XY листа, мм?\n\n"
            f"Плоскость {self.plane.currentText()} и её смещение {self.plane_offset.value():.3f} мм "
            "в DXF не сохраняются. Файл не связан с проектом и не является 3D-деталью.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        suggested = str(self._path.with_suffix(".dxf")) if self._path else "эскиз.dxf"
        path, _ = QFileDialog.getSaveFileName(self, "Экспортировать новый DXF", suggested,
                                              "DXF (*.dxf)", options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return False
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".dxf")
        try:
            write_new_dxf(target, self._document())
        except (SketchDxfError, OSError) as exc:
            QMessageBox.warning(self, "Экспорт не выполнен", f"{exc}\nВыберите новое имя файла.")
            return False
        self._message(f"DXF экспортирован: {target}; эскиз не сохранён автоматически")
        return True

    def _confirm_discard(self) -> bool:
        if self._allow_close or not self._dirty():
            return True
        answer = QMessageBox.question(self, "Несохранённый эскиз", "Сохранить изменения перед продолжением?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                                      QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            return self._save()
        return answer == QMessageBox.StandardButton.No

    def _load_document(self, doc: SketchDocument, path: Path | None) -> None:
        self._clear_diagnostics()
        self.canvas.draft = SketchDraft(doc.entities)
        self.canvas.pending = None
        self.canvas.measure_start = None
        self.canvas.hover = None
        self.canvas.selected = None
        self.canvas.construction_indices.clear()
        self.canvas.plane_locked = bool(doc.entities)
        self.plane.setCurrentText(doc.plane)
        self.plane_offset.setValue(doc.offset_mm)
        self._path = path
        self._saved = self._document()
        self._message("Эскиз открыт" if path else "Новый эскиз")
        if path and doc.entities:
            self.canvas.fit_view()
        self.canvas.update()

    def _new(self) -> None:
        if self._confirm_discard():
            self._load_document(SketchDocument("XY", 0.0, ()), None)

    def _open(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Открыть эскиз", "", "Эскиз Подвеска.Про (*.slsketch)")
        if not path:
            return
        try:
            doc = read_sketch(path)
        except (SketchIOError, OSError) as exc:
            QMessageBox.warning(self, "Не удалось открыть эскиз", str(exc))
            return
        self._load_document(doc, Path(path))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.canvas.cancel()
            event.accept()
        else:
            super().keyPressEvent(event)

    def reject(self) -> None:
        if self._confirm_discard():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self._allow_close = True
        try:
            super().closeEvent(event)
        finally:
            self._allow_close = False
