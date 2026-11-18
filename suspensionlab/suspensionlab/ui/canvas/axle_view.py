"""Схема подвески: векторная отрисовка проекций на QPainter.

Виджет показывает реальную геометрию из модели: точки крепления, рычаги,
кулак, колесо, пружину, амортизатор. Никакой физики здесь нет — модуль
только проецирует координаты на плоскость выбранного вида и рисует их.
Кинематические метрики и деформированные положения появятся в ядре
расчёта (этап M1) и будут отображаться поверх этой же схемы.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from ...core.powertrain_layout import layout_diagram
from ...core.wheel_projection import wheel_projection
from ...i18n import tr
from ...model.entities import Axle
from ..controller import AppController, Selection
from ..theme import canvas_colors

#: Виды схемы.
VIEW_MODES = ("front", "side", "top")

#: Шаг сетки в миллиметрах.
GRID_STEP_MM = 50.0

#: Радиус попадания курсора в точку, пиксели.
HIT_RADIUS_PX = 9.0


@dataclass(slots=True)
class _Projection:
    """Плоскость проекции: какие координаты модели дают экранные оси."""

    name: str
    horizontal: str
    vertical: str
    horizontal_sign: float
    vertical_sign: float


_PROJECTIONS: dict[str, _Projection] = {
    "front": _Projection("front", "y", "z", -1.0, 1.0),
    "side": _Projection("side", "x", "z", -1.0, 1.0),
    "top": _Projection("top", "x", "y", -1.0, 1.0),
}


class AxleCanvas(QWidget):
    """Интерактивная схема подвески с зумом и панорамированием."""

    viewChanged = Signal(str)

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._mode = "front"
        self._roles: tuple[str, ...] = ("front",)
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._base_scale = 0.3
        self._fit_pending = True
        self._hovered: tuple[str, str] | None = None
        self._dragging = False
        self._drag_last = QPointF()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(320, 240)
        self._layout_key = self._powertrain_key()

        controller.modelChanged.connect(self._on_model_changed)
        controller.projectReplaced.connect(self._request_fit)
        controller.selectionChanged.connect(lambda _selection: self.update())

    # ------------------------------------------------------------------ настройки
    def set_view_mode(self, mode: str) -> None:
        """Переключает проекцию (спереди / сбоку / сверху)."""
        if mode not in VIEW_MODES or mode == self._mode:
            return
        self._mode = mode
        self._request_fit()
        self.viewChanged.emit(mode)
        self.update()

    def view_mode(self) -> str:
        """Текущая проекция."""
        return self._mode

    def set_roles(self, roles: tuple[str, ...]) -> None:
        """Задаёт, какие оси показывать (одну или обе)."""
        if roles == self._roles:
            return
        self._roles = roles
        self._request_fit()
        self.update()

    def roles(self) -> tuple[str, ...]:
        """Показанные оси."""
        return self._roles

    def _powertrain_key(self) -> tuple[str, float, bool, bool]:
        project = self._controller.project
        return (project.vehicle.powertrain_layout, project.vehicle.wheelbase_mm,
                project.front.drivetrain.driven, project.rear.drivetrain.driven)

    def _on_model_changed(self) -> None:
        key = self._powertrain_key()
        if key != self._layout_key:
            self._layout_key = key
            self._request_fit()
        self.update()

    def _request_fit(self) -> None:
        """Просит выполнить вписывание при следующей отрисовке."""
        self._fit_pending = True
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)

    def fit_to_view(self) -> None:
        """Вписывает всю схему в окно."""
        self._request_fit()
        self.update()

    def zoom_by(self, factor: float) -> None:
        """Масштабирует схему относительно центра."""
        self._zoom = max(0.15, min(8.0, self._zoom * factor))
        self.update()

    def zoom(self) -> float:
        """Текущий масштаб (1.0 — вписанная схема)."""
        return self._zoom

    # ------------------------------------------------------------------ проекция
    def _axle_offset(self, role: str) -> float:
        """Смещение оси по X: при показе двух осей задняя отодвигается на базу.

        В видах сбоку и сверху оси иначе накладываются друг на друга;
        смещение делает картину похожей на реальную компоновку автомобиля.
        """
        if len(self._roles) < 2 or role == "front":
            return 0.0
        if self._mode not in ("side", "top"):
            return 0.0
        return -float(self._controller.project.vehicle.wheelbase_mm)

    def _projection(self) -> _Projection:
        """Активная плоскость проекции."""
        return _PROJECTIONS[self._mode]

    def _project(self, x: float, y: float, z: float) -> tuple[float, float]:
        """Проецирует точку модели в координаты плоскости (мм)."""
        p = self._projection()
        values = {"x": x, "y": y, "z": z}
        return (p.horizontal_sign * values[p.horizontal], p.vertical_sign * values[p.vertical])

    def _to_screen(self, u: float, v: float) -> QPointF:
        """Переводит координаты плоскости в пиксели окна."""
        scale = self._scale()
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        return QPointF(
            center.x() + self._pan.x() + u * scale,
            center.y() + self._pan.y() - v * scale,
        )

    def _scale(self) -> float:
        """Текущий масштаб в пикселях на миллиметр."""
        return self._base_scale * self._zoom

    def _axle_project(self, axle, x: float, y: float, z: float) -> tuple[float, float]:
        """Проекция точки оси с учётом смещения задней оси."""
        return self._project(x + self._axle_offset(axle.role), y, z)

    def _global_project(self, x: float, y: float, z: float) -> tuple[float, float]:
        """Общие координаты схемы привода в локальный вид выбранной оси."""
        if self._roles == ("rear",) and self._mode in ("side", "top"):
            x += self._controller.project.vehicle.wheelbase_mm
        return self._project(x, y, z)

    def _collect_bounds(self) -> tuple[float, float, float, float]:
        """Границы геометрии в координатах плоскости (umin, umax, vmin, vmax)."""
        us: list[float] = []
        vs: list[float] = []
        for role in self._roles:
            axle = self._controller.project.axle(role)
            for code, point in axle.hardpoints.items():
                spec = axle.spec.point(code)
                if code == "driveshaft_front" or (spec is not None and spec.group == "drivetrain" and not axle.drivetrain.driven):
                    continue
                u, v = self._axle_project(axle, point.x, point.y, point.z)
                us.append(u)
                vs.append(v)
                u2, v2 = self._axle_project(axle, point.x, -point.y, point.z)
                if not axle.has_explicit_sides:
                    us.append(u2)
                    vs.append(v2)
            radius = axle.wheel.r_dynamic_mm
            wheel_code = axle.wheel_center_code()
            if wheel_code:
                point = axle.hardpoints[wheel_code]
                centers = [point.as_tuple()]
                if axle.has_explicit_sides:
                    right = axle.hardpoints.get("wheel_center_r")
                    if right is not None:
                        centers.append(right.as_tuple())
                else:
                    centers.append((point.x, -point.y, point.z))
                _, half_u, half_v = wheel_projection(self._mode, radius, axle.wheel.width_mm)
                for x, y, z in centers:
                    u, v = self._axle_project(axle, x, y, z)
                    us.extend([u - half_u, u + half_u])
                    vs.extend([v - half_v, v + half_v])
        if self._mode in ("side", "top"):
            diagram = layout_diagram(self._controller.project)
            for component in diagram.components:
                for p3 in (component.low, component.high):
                    u, v = self._global_project(*p3)
                    us.append(u)
                    vs.append(v)
            for shaft in diagram.shafts:
                if shaft.role in self._roles:
                    for p3 in (shaft.start, shaft.end):
                        u, v = self._global_project(*p3)
                        us.append(u)
                        vs.append(v)
        if not us:
            return (-500.0, 500.0, -200.0, 600.0)
        return (min(us), max(us), min(vs), max(vs))

    def _update_fit(self) -> None:
        """Вычисляет масштаб так, чтобы геометрия помещалась в окно."""
        umin, umax, vmin, vmax = self._collect_bounds()
        width = max(1.0, umax - umin)
        height = max(1.0, vmax - vmin)
        margin = 0.86
        scale = min(self.width() * margin / width, self.height() * margin / height)
        self._base_scale = max(0.02, scale)
        center_u = (umin + umax) / 2.0
        center_v = (vmin + vmax) / 2.0
        self._pan = QPointF(-center_u * self._base_scale, center_v * self._base_scale)
        self._fit_pending = False

    # ------------------------------------------------------------------ отрисовка
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Рисует схему."""
        if self._fit_pending:
            self._update_fit()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = canvas_colors(self._controller.project.view.theme)
        painter.fillRect(self.rect(), QColor(colors.background))
        self._draw_grid(painter, colors)
        self._draw_powertrain(painter, colors)
        for role in self._roles:
            self._draw_axle(painter, self._controller.project.axle(role), colors)
        self._draw_legend(painter, colors)
        painter.end()

    def _draw_grid(self, painter: QPainter, colors) -> None:
        """Сетка с шагом 50 мм и масштабная линейка."""
        scale = self._scale()
        if scale <= 0:
            return
        step_px = GRID_STEP_MM * scale
        if step_px < 8.0:
            return
        pen = QPen(QColor(colors.grid))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        center = QPointF(self.width() / 2.0 + self._pan.x(), self.height() / 2.0 + self._pan.y())
        index = 0
        x = center.x() % step_px
        while x < self.width():
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            x += step_px
            index += 1
        y = center.y() % step_px
        while y < self.height():
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
            y += step_px

        # земля и ось симметрии
        if self._mode in ("front", "side"):
            ground_pen = QPen(QColor(colors.ground), 1.6)
            ground_pen.setStyle(Qt.PenStyle.DashDotLine)
            painter.setPen(ground_pen)
            point = self._to_screen(0.0, 0.0)
            painter.drawLine(QPointF(0, point.y()), QPointF(self.width(), point.y()))
        if self._mode in ("front", "top"):
            axis_pen = QPen(QColor(colors.axis), 1.0)
            axis_pen.setStyle(Qt.PenStyle.DashDotLine)
            painter.setPen(axis_pen)
            point = self._to_screen(0.0, 0.0)
            painter.drawLine(QPointF(point.x(), 0), QPointF(point.x(), self.height()))

        self._draw_scale_bar(painter, colors)

    def _draw_scale_bar(self, painter: QPainter, colors) -> None:
        """Масштабная линейка 100 мм в левом нижнем углу."""
        scale = self._scale()
        length_mm = 100.0
        while length_mm * scale > 180 and length_mm > 10:
            length_mm /= 2
        pixels = length_mm * scale
        x0, y0 = 16.0, self.height() - 14.0
        pen = QPen(QColor(colors.hint), 1.4)
        painter.setPen(pen)
        painter.drawLine(QPointF(x0, y0), QPointF(x0 + pixels, y0))
        painter.drawLine(QPointF(x0, y0 - 4), QPointF(x0, y0 + 4))
        painter.drawLine(QPointF(x0 + pixels, y0 - 4), QPointF(x0 + pixels, y0 + 4))
        painter.setFont(QFont(self.font().family(), 9))
        painter.drawText(QRectF(x0, y0 - 20, 140, 16), int(Qt.AlignmentFlag.AlignLeft), f"{length_mm:.0f} {tr('unit.length.mm')}")

    def _draw_powertrain(self, painter: QPainter, colors) -> None:
        """Показывает только условную компоновку, не редактируемую геометрию агрегатов."""
        if self._mode not in ("side", "top"):
            return
        diagram = layout_diagram(self._controller.project)
        painter.setPen(QPen(QColor(colors.hint)))
        painter.setFont(QFont(self.font().family(), 9))
        painter.drawText(QRectF(14, 8, self.width() - 28, 34),
                         int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap),
                         tr(f"powertrain.status.{diagram.status}"))
        if diagram.status != "ok":
            return
        for part in diagram.components:
            a = self._to_screen(*self._global_project(*part.low))
            b = self._to_screen(*self._global_project(*part.high))
            rect = QRectF(a, b).normalized()
            fill = QColor(colors.damper)
            fill.setAlpha(45)
            painter.setBrush(fill)
            pen = QPen(QColor(colors.damper), 1.3)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QPen(QColor(colors.label)))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), tr(f"powertrain.part.{part.kind}"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(colors.damper), 3.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        for shaft in diagram.shafts:
            if shaft.role in self._roles:
                painter.drawLine(self._to_screen(*self._global_project(*shaft.start)),
                                 self._to_screen(*self._global_project(*shaft.end)))

    def _draw_wheels(self, painter: QPainter, axle: Axle, colors) -> None:
        """Ортографический профиль: фронт/верх — прямоугольник, бок — круг."""
        painter.setPen(QPen(QColor(colors.wheel), 1.8))
        fill = QColor(colors.wheel_fill)
        fill.setAlpha(90)
        painter.setBrush(fill)
        shape, half_u, half_v = wheel_projection(self._mode, axle.wheel.r_dynamic_mm, axle.wheel.width_mm)
        for side in (1.0, -1.0):
            code = ("wheel_center_l" if side > 0 else "wheel_center_r") if axle.has_explicit_sides else axle.wheel_center_code()
            if code is None or code not in axle.hardpoints:
                continue
            point = axle.hardpoints[code]
            y = point.y if axle.has_explicit_sides else point.y * side
            center = self._to_screen(*self._axle_project(axle, point.x, y, point.z))
            rect = QRectF(center.x() - half_u * self._scale(), center.y() - half_v * self._scale(),
                          2 * half_u * self._scale(), 2 * half_v * self._scale())
            if shape == "ellipse":
                painter.drawEllipse(rect)
            else:
                painter.drawRect(rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_axle(self, painter: QPainter, axle: Axle, colors) -> None:
        """Рисует одну ось во всех слоях."""
        sides = (1.0,) if axle.has_explicit_sides else (1.0, -1.0)
        radius = axle.wheel.r_dynamic_mm

        self._draw_wheels(painter, axle, colors)

        # кузов / подрамник: вертикальная линия по внутренним опорам
        body_pen = QPen(QColor(colors.body), 1.2)
        body_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(body_pen)
        inner = [p for code, p in axle.hardpoints.items()
                 if code != "driveshaft_front" and (point_spec := axle.spec.point(code)) is not None
                 and point_spec.role == "body" and (point_spec.group != "drivetrain" or axle.drivetrain.driven)]
        if inner:
            projections = [self._axle_project(axle, p.x, p.y, p.z) for p in inner]
            vmins = min(v[1] for v in projections)
            vmaxs = max(v[1] for v in projections)
            u_mount = max(v[0] for v in projections)
            for mount in (u_mount, -u_mount):
                if len(self._roles) > 1 and self._mode in ("side", "top"):
                    continue
                top = self._to_screen(mount, vmaxs + 60.0)
                bottom = self._to_screen(mount, vmins - 60.0)
                painter.drawLine(top, bottom)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # рычаги и тяги
        link_pen = QPen(QColor(colors.link), 2.4)
        painter.setPen(link_pen)
        for link_spec in axle.spec.links:
            if link_spec.code in ("driveshaft_to_differential", "driveshaft"):
                continue  # Старый условный кардан не задаёт компоновку всего автомобиля.
            if link_spec.group == "drivetrain" and not axle.drivetrain.driven:
                continue
            for side in sides:
                if axle.has_explicit_sides:
                    segments = axle.link_endpoints(link_spec.code)
                else:
                    segments = self._mirror_segments(axle, link_spec.code, side)
                for start, end in segments:
                    painter.drawLine(
                        self._to_screen(*self._axle_project(axle, *start)),
                        self._to_screen(*self._axle_project(axle, *end)),
                    )

        # пружина и амортизатор
        for code_in, code_out, color in (
            ("spring_lo", "spring_up", colors.spring),
            ("damper_lo", "damper_up", colors.damper),
        ):
            for side in (1.0, -1.0):
                points = self._pair_points(axle, code_in, code_out, side)
                if points is None:
                    continue
                start_screen = self._to_screen(*self._axle_project(axle, *points[0]))
                end_screen = self._to_screen(*self._axle_project(axle, *points[1]))
                pen = QPen(QColor(color), 1.8)
                painter.setPen(pen)
                if code_in.startswith("spring"):
                    self._draw_spring(painter, start_screen, end_screen, QColor(color))
                else:
                    painter.drawLine(start_screen, end_screen)

        # точки крепления
        for code in axle.point_codes():
            if code == "driveshaft_front" or code not in axle.hardpoints:
                continue
            point_spec = axle.spec.point(code)
            if point_spec is not None and point_spec.group == "drivetrain" and not axle.drivetrain.driven:
                continue
            point = axle.hardpoints[code]
            for side in sides:
                y = point.y if axle.has_explicit_sides else point.y * side
                u, v = self._axle_project(axle, point.x, y, point.z)
                screen = self._to_screen(u, v)
                selected = self._is_selected(axle, code)
                hovered = self._hovered == (axle.role, code)
                color = colors.point_selected if (selected or hovered) else colors.point
                if point.locked:
                    color = colors.point_locked
                painter.setPen(QPen(QColor(colors.background), 1.0))
                painter.setBrush(QColor(color))
                radius_px = 5.0 if selected or hovered else 3.4
                painter.drawEllipse(screen, radius_px, radius_px)
                if (selected or hovered) and (side > 0 or axle.has_explicit_sides):
                    painter.setFont(QFont(self.font().family(), 9))
                    painter.setPen(QPen(QColor(colors.label)))
                    point_spec = axle.spec.point(code)
                    label = tr(point_spec.name_key) if point_spec else code
                    offset = QPointF(9.0, -9.0) if screen.x() < self.width() - 180 else QPointF(-150.0, -9.0)
                    painter.drawText(screen + offset, label)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # подпись оси — над колесом
        painter.setPen(QPen(QColor(colors.label)))
        painter.setFont(QFont(self.font().family(), 10, QFont.Weight.DemiBold))
        title = tr("canvas.front") if axle.role == "front" else tr("canvas.rear")
        wheel_code = axle.wheel_center_code()
        if wheel_code is not None:
            point = axle.hardpoints[wheel_code]
            u, v = self._axle_project(axle, point.x, point.y, point.z)
            anchor = self._to_screen(u, v)
            anchor = QPointF(anchor.x(), anchor.y() - radius * self._scale() - 8.0)
            painter.drawText(QRectF(anchor.x() - 80.0, anchor.y() - 14.0, 200.0, 16.0), int(Qt.AlignmentFlag.AlignLeft), title)
        else:
            painter.drawText(QRectF(14, 10, 260, 18), int(Qt.AlignmentFlag.AlignLeft), title)

    def _mirror_segments(
        self, axle: Axle, link_code: str, side: float
    ) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
        """Отрезки рычага с учётом зеркальной стороны."""
        result = []
        for start, end in axle.link_endpoints(link_code):
            result.append(
                (
                    (start[0], start[1] * side, start[2]),
                    (end[0], end[1] * side, end[2]),
                )
            )
        return result

    def _pair_points(self, axle: Axle, code_in: str, code_out: str, side: float):
        """Пара точек (низ, верх) для пружины/амортизатора с учётом стороны."""
        if axle.has_explicit_sides:
            suffix = "_l" if side > 0 else "_r"
            first = axle.hardpoints.get(code_in + suffix)
            second = axle.hardpoints.get(code_out + suffix)
            if first is None or second is None:
                return None
            return (first.as_tuple(), second.as_tuple())
        first = axle.hardpoints.get(code_in)
        second = axle.hardpoints.get(code_out)
        if first is None or second is None:
            return None
        a = (first.x, first.y * side, first.z)
        b = (second.x, second.y * side, second.z)
        return (a, b)

    def _draw_spring(self, painter: QPainter, start: QPointF, end: QPointF, color: QColor) -> None:
        """Рисует пружину в виде зигзага между опорами."""
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 4.0:
            return
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux
        amplitude = min(7.0, max(2.5, length * 0.12))
        coils = max(4, int(length / 12))
        path = QPainterPath(start)
        for index in range(1, coils):
            t = index / coils
            direction = 1.0 if index % 2 else -1.0
            px = start.x() + ux * length * t + nx * amplitude * direction
            py = start.y() + uy * length * t + ny * amplitude * direction
            path.lineTo(px, py)
        path.lineTo(end)
        painter.setPen(QPen(color, 1.4))
        painter.drawPath(path)

    def _draw_legend(self, painter: QPainter, colors) -> None:
        """Подпись с подсказкой по управлению."""
        painter.setPen(QPen(QColor(colors.hint)))
        painter.setFont(QFont(self.font().family(), 9))
        hint = tr("canvas.hint")
        painter.drawText(
            QRectF(14, self.height() - 26, self.width() - 28, 16),
            int(Qt.AlignmentFlag.AlignRight),
            hint,
        )

    # ------------------------------------------------------------------ мышь
    def _is_selected(self, axle: Axle, code: str) -> bool:
        """Выбрана ли эта точка."""
        selection = self._controller.selection
        return bool(selection and selection.kind == "point" and selection.role == axle.role and selection.code == code)

    def _hit_test(self, position: QPointF) -> tuple[str, str] | None:
        """Ищет точку крепления рядом с курсором."""
        best: tuple[str, str] | None = None
        best_distance = HIT_RADIUS_PX
        for role in self._roles:
            axle = self._controller.project.axle(role)
            sides = (1.0,) if axle.has_explicit_sides else (1.0, -1.0)
            for code in axle.point_codes():
                if code == "driveshaft_front" or code not in axle.hardpoints:
                    continue
                point_spec = axle.spec.point(code)
                if point_spec is not None and point_spec.group == "drivetrain" and not axle.drivetrain.driven:
                    continue
                point = axle.hardpoints[code]
                for side in sides:
                    y = point.y if axle.has_explicit_sides else point.y * side
                    screen = self._to_screen(*self._axle_project(axle, point.x, y, point.z))
                    distance = math.hypot(screen.x() - position.x(), screen.y() - position.y())
                    if distance < best_distance:
                        best_distance = distance
                        best = (role, code)
        return best

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        """Выбор точки или начало панорамирования."""
        position = event.position()
        hit = self._hit_test(position)
        if hit is not None and event.button() == Qt.MouseButton.LeftButton:
            role, code = hit
            self._controller.select(Selection("point", role, code))
            self.update()
            return
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._dragging = True
            self._drag_last = position
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        """Панорамирование и подсветка точки под курсором."""
        position = event.position()
        if self._dragging:
            delta = position - self._drag_last
            self._pan += delta
            self._drag_last = position
            self.update()
            return
        hit = self._hit_test(position)
        if hit != self._hovered:
            self._hovered = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        """Завершение панорамирования."""
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt API)
        """Зум колесом мыши к курсору."""
        steps = event.angleDelta().y() / 120.0
        if steps == 0:
            return
        position = event.position()
        anchor_u, anchor_v = self._screen_to_model(position)
        self._zoom = max(0.15, min(8.0, self._zoom * (1.15**steps)))
        scale = self._scale()
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        self._pan = QPointF(
            position.x() - center.x() - anchor_u * scale,
            position.y() - center.y() + anchor_v * scale,
        )
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """При изменении размера схема заново вписывается в окно."""
        super().resizeEvent(event)
        if self._zoom == 1.0:
            self._fit_pending = True
            self.update()

    def _screen_to_model(self, position: QPointF) -> tuple[float, float]:
        """Обратное преобразование экран → плоскость (мм)."""
        scale = self._scale()
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        u = (position.x() - center.x() - self._pan.x()) / scale
        v = -(position.y() - center.y() - self._pan.y()) / scale
        return (u, v)
