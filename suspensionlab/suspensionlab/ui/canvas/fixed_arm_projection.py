"""Ортогональная проекция скелета: перетаскивание только вершин изгиба."""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ...core.pose_view import Point
from ...model.fixed_arm_skeleton import SkeletonPreview
from .fixed_arm_pick import straight_leg_hits
from .fixed_arm_scene import LABELS


@dataclass
class _Drag:
    code: str
    point: Point
    start: QPointF
    current: QPointF
    scale: float
    size: tuple[int, int]
    moved: bool = False


class SkeletonProjection(QWidget):
    """При перетаскивании показывает призрак; кандидат принимается после отпускания."""

    pointPicked = Signal(str)
    ambiguousPick = Signal()
    dragStarted = Signal(str)
    dragCancelled = Signal()
    dragReleased = Signal(str, object, object)  # код, индексы осей, новые XYZ
    dragMoved = Signal(str, object)
    segmentPicked = Signal(str, object)
    dimensionsApplied = Signal(str, object, object)

    def __init__(self, axes: tuple[int, int], parent: QWidget | None = None, *,
                 outer_title: str = 'До шаровой', outer_label: str = 'Шаровая') -> None:
        super().__init__(parent)
        self.axes = axes
        self._outer_label = outer_label
        self.preview: SkeletonPreview | None = None
        self.points: tuple[tuple[str, Point], ...] = ()
        self.selected_point: str | None = None
        self._drag: _Drag | None = None
        self._segment_start: QPointF | None = None
        self.setMinimumSize(380, 240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName('Проекция скелета ' + ''.join('XYZ'[i] for i in axes))
        self._dimension_point: Point | None = None
        self._dimension_anchor: Point | None = None
        self._dimension_ball: Point | None = None
        self._dimension_texts: tuple[str, str] = ('', '')
        self._distance_texts: tuple[str, str] = ('', '')
        self._dimensions = QFrame(self)
        self._dimensions.setFrameShape(QFrame.Shape.StyledPanel)
        self._dimensions.setAutoFillBackground(True)
        self._dimensions.setMaximumWidth(300)
        form = QVBoxLayout(self._dimensions)
        form.setContentsMargins(6, 4, 6, 4)
        form.setSpacing(3)
        self._dimension_title = QLabel('От своей опоры, мм', self._dimensions)
        form.addWidget(self._dimension_title)
        row = QHBoxLayout()
        self._dimension_fields: list[QLineEdit] = []
        for axis in axes:
            row.addWidget(QLabel('Δ' + 'XYZ'[axis], self._dimensions))
            field = QLineEdit(self._dimensions)
            field.setObjectName('projection_offset_' + 'XYZ'[axis])
            field.setAccessibleName('Смещение ' + 'XYZ'[axis] + ' от своей опоры, мм')
            field.setMaximumWidth(95)
            field.setMaxLength(64)
            field.installEventFilter(self)
            self._dimension_fields.append(field)
            row.addWidget(field)
        form.addLayout(row)
        offset_buttons = QHBoxLayout()
        apply_button = QPushButton('Применить смещения', self._dimensions)
        apply_button.setAutoDefault(False)
        apply_button.clicked.connect(self._apply_dimensions)
        offset_buttons.addWidget(apply_button)
        reset_button = QPushButton('Сброс ввода', self._dimensions)
        reset_button.setAutoDefault(False)
        reset_button.setToolTip('Вернуть поля к значениям текущей геометрии без её изменения')
        reset_button.clicked.connect(self._reset_dimensions)
        offset_buttons.addWidget(reset_button)
        form.addLayout(offset_buttons)
        self._dimension_distances = QLabel('В проекции, мм · не длина трубы\nДвижение вдоль текущего луча', self._dimensions)
        self._dimension_distances.setWordWrap(True)
        self._dimension_distances.setToolTip('Вершина движется от выбранной опоры по текущему направлению на этой '
                                             'проекции. Скрытая координата не изменяется. Это не длины труб.')
        form.addWidget(self._dimension_distances)
        self._distance_fields: list[QLineEdit] = []
        for index, title in enumerate(('До опоры', outer_title)):
            distance_row = QHBoxLayout()
            distance_row.addWidget(QLabel(title, self._dimensions))
            field = QLineEdit(self._dimensions)
            field.setObjectName('projection_distance_' + ('anchor' if index == 0 else 'ball'))
            field.setAccessibleName(title + ', проекционное расстояние, мм')
            field.setMaximumWidth(95)
            field.setMaxLength(64)
            field.installEventFilter(self)
            self._distance_fields.append(field)
            distance_row.addWidget(field)
            button = QPushButton('↵', self._dimensions)
            button.setFixedWidth(32)
            button.setToolTip('Применить только это расстояние')
            button.setAccessibleName('Применить расстояние ' + title)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, i=index: self._apply_distance(i))
            distance_row.addWidget(button)
            form.addLayout(distance_row)
        self._dimension_error = QLabel(self._dimensions)
        self._dimension_error.setWordWrap(True)
        self._dimension_error.hide()
        form.addWidget(self._dimension_error)
        self._dimensions.hide()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if watched in self._dimension_fields:
                self._apply_dimensions()
                return True
            if watched in self._distance_fields:
                self._apply_distance(self._distance_fields.index(watched))
                return True
        return super().eventFilter(watched, event)

    def _cancel_drag(self) -> None:
        self._segment_start = None
        if self._drag is not None:
            self._drag = None
            self.dragCancelled.emit()
            self.update()

    def set_preview(self, preview: SkeletonPreview | None, points: tuple[tuple[str, Point], ...] = ()) -> None:
        self._cancel_drag()
        self._segment_start = None
        self.preview = preview
        self.points = points if preview is not None else ()
        self.selected_point = None
        self._dimensions.hide()
        self._dimension_point = None
        self.update()

    def select_point(self, code: str | None) -> None:
        self.selected_point = code
        self._dimensions.hide()
        self._dimension_point = None
        if self.preview is not None and code in ('bend_front', 'bend_rear'):
            point = next((point for name, point in self.points if name == code), None)
            if point is not None and len(self.preview.anchors) >= 3:
                anchor = self.preview.anchors[0 if code == 'bend_front' else 1]
                ball = self.preview.anchors[2]
                self._dimension_point, self._dimension_anchor, self._dimension_ball = point, anchor, ball
                texts = tuple(repr(point[axis] - anchor[axis]) for axis in self.axes)
                self._dimension_texts = (texts[0], texts[1])
                for field, text in zip(self._dimension_fields, self._dimension_texts, strict=True):
                    field.setText(text)
                a, b = self.axes
                first = hypot(point[a] - anchor[a], point[b] - anchor[b])
                second = hypot(point[a] - ball[a], point[b] - ball[b])
                self._distance_texts = (f'{first:.4f}', f'{second:.4f}')
                for field, text in zip(self._distance_fields, self._distance_texts, strict=True):
                    field.setText(text)
                self._dimension_error.hide()
                self._dimensions.adjustSize()
                self._place_dimensions()
                self._dimensions.show()
                self._dimensions.raise_()
        self.update()

    def _place_dimensions(self) -> None:
        if self._dimension_point is None or self.preview is None:
            return
        pos = self._screen_point(self._dimension_point)
        panel_width = min(self._dimensions.sizeHint().width(), max(1, self.width() - 16))
        panel_height = self._dimensions.sizeHint().height()
        right = max(8., self.width() - panel_width - 8.)
        bottom = max(8., self.height() - panel_height - 24.)
        near_x = min(max(8., pos.x() + 18), right)
        near_y = min(max(8., pos.y() - panel_height / 2), bottom)
        candidates = [(near_x, near_y), (8., 8.), (right, 8.), (8., bottom), (right, bottom)]
        markers = [self._screen_point(point) for _, point in self.points]
        line_points: list[QPointF] = []
        for path in self.preview.centerlines:
            projected = [self._screen_point(point) for point in path]
            for first, second in zip(projected, projected[1:], strict=False):
                line_points.extend(first + (second - first) * (step / 8) for step in range(9))
        def score(candidate: tuple[float, float]) -> tuple[int, float]:
            x, y = candidate
            rect = QRectF(x, y, panel_width, panel_height).adjusted(-12, -12, 12, 12)
            # Avoid blocking markers first, then avoid covering displayed paths.
            obstruction = 1000 * sum(rect.contains(marker) for marker in markers)
            obstruction += sum(rect.contains(point) for point in line_points)
            distance = hypot(x + panel_width / 2 - pos.x(), y + panel_height / 2 - pos.y())
            return obstruction, distance
        x, y = min(candidates, key=score)
        self._dimensions.setGeometry(int(x), int(y), panel_width, panel_height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_dimensions()

    def _reset_dimensions(self) -> None:
        for field, text in zip(self._dimension_fields, self._dimension_texts, strict=True):
            field.setText(text)
        for field, text in zip(self._distance_fields, self._distance_texts, strict=True):
            field.setText(text)
        self._dimension_error.hide()
        self._place_dimensions()

    def _show_dimension_error(self, message: str) -> None:
        self._dimension_error.setText(message)
        self._dimension_error.show()
        self._place_dimensions()

    def _apply_dimensions(self) -> None:
        if self.selected_point not in ('bend_front', 'bend_rear') or self._dimension_point is None or self._dimension_anchor is None:
            return
        if any(field.text() != initial for field, initial in zip(self._distance_fields, self._distance_texts, strict=True)):
            self._show_dimension_error('Сначала верните изменённые расстояния к показанным значениям.')
            return
        try:
            offsets = tuple(float(field.text().strip().replace(',', '.')) for field in self._dimension_fields)
            if not all(isfinite(value) for value in offsets):
                raise ValueError
        except ValueError:
            self._show_dimension_error('Введите конечные числа в миллиметрах.')
            return
        self._dimension_error.hide()
        result = list(self._dimension_point)
        for index, axis in enumerate(self.axes):
            # Preserve exact coordinates when an untouched displayed offset is submitted.
            if self._dimension_fields[index].text() != self._dimension_texts[index]:
                result[axis] = self._dimension_anchor[axis] + offsets[index]
        self.dimensionsApplied.emit(self.selected_point, self.axes, tuple(result))

    def _apply_distance(self, index: int) -> None:
        if (index not in (0, 1) or self.selected_point not in ('bend_front', 'bend_rear') or
                self._dimension_point is None or self._dimension_anchor is None or self._dimension_ball is None):
            return
        if (any(field.text() != initial for field, initial in zip(self._dimension_fields, self._dimension_texts, strict=True)) or
                self._distance_fields[1 - index].text() != self._distance_texts[1 - index]):
            self._show_dimension_error('Сначала верните остальные изменённые размеры к показанным значениям.')
            return
        try:
            value = float(self._distance_fields[index].text().strip().replace(',', '.'))
            if not isfinite(value) or not 0 < value <= 1_000_000:
                raise ValueError
        except ValueError:
            self._show_dimension_error('Расстояние должно быть конечным и положительным, не более 1 000 000 мм.')
            return
        if self._distance_fields[index].text() == self._distance_texts[index]:
            self._dimension_error.hide()
            return
        reference = (self._dimension_anchor, self._dimension_ball)[index]
        point = self._dimension_point
        a, b = self.axes
        current = hypot(point[a] - reference[a], point[b] - reference[b])
        if current < 1e-9:
            self._show_dimension_error('Направление в проекции не определено: сначала сместите вершину от этой точки.')
            return
        result = list(point)
        for axis in self.axes:
            result[axis] = reference[axis] + (point[axis] - reference[axis]) * value / current
        self._dimension_error.hide()
        self.dimensionsApplied.emit(self.selected_point, self.axes, tuple(result))

    def _transform(self) -> tuple[float, float, float]:
        if self.preview is None:
            raise ValueError('Нет скелета')
        a, b = self.axes
        points = [p for path in self.preview.centerlines for p in path]
        points.extend(p for _, p in self.points)
        low_x, high_x = min(p[a] for p in points), max(p[a] for p in points)
        low_y, high_y = min(p[b] for p in points), max(p[b] for p in points)
        scale = min(max(self.width() - 100, 1) / max(high_x - low_x, 1),
                    max(self.height() - 80, 1) / max(high_y - low_y, 1))
        return (low_x + high_x) / 2, (low_y + high_y) / 2, scale

    def _screen_point(self, point: Point) -> QPointF:
        cx, cy, scale = self._transform()
        a, b = self.axes
        return QPointF(self.width() / 2 + (point[a] - cx) * scale,
                       self.height() / 2 - (point[b] - cy) * scale)

    def _point_hits(self, position: QPointF) -> tuple[str, ...]:
        if self.preview is None:
            return ()
        result = []
        for code, point in self.points:
            delta = self._screen_point(point) - position
            if delta.x() ** 2 + delta.y() ** 2 <= 12 ** 2:
                result.append(code)
        return tuple(result)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        if self.preview is None:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), 'Нет актуального скелета')
            return
        painter.setPen(QPen(QColor('#388aac'), 3))
        for path in self.preview.centerlines:
            painter.drawPolyline(QPolygonF([self._screen_point(p) for p in path]))
        if self._dimension_point is not None and self._dimension_anchor is not None:
            anchor_pos = self._screen_point(self._dimension_anchor)
            vertex_pos = self._screen_point(self._dimension_point)
            corner = QPointF(vertex_pos.x(), anchor_pos.y())
            painter.setPen(QPen(QColor('#e38d27'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(anchor_pos, corner)
            painter.drawLine(corner, vertex_pos)
        for code, point in self.points:
            pos = self._screen_point(point)
            color = QColor('#ed9c2e' if code.startswith('bend_') else '#2da9b5')
            if self.selected_point == code:
                painter.setPen(QPen(QColor('#ffd43b'), 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(pos, 8, 8)
            painter.setPen(QPen(color.darker(170), 1))
            painter.setBrush(color)
            painter.drawEllipse(pos, 4, 4)
            painter.setPen(self.palette().text().color())
            label = self._outer_label if code == 'lbj' else LABELS[code]
            width = painter.fontMetrics().horizontalAdvance(label)
            x = pos.x() + 7
            if x + width > self.width() - 6:
                x = pos.x() - width - 7
            x = max(4., min(x, self.width() - width - 4.))
            y = max(18., min(pos.y() - 7, self.height() - 32.))
            painter.drawText(QPointF(x, y), label)
        if self._drag is not None and self._drag.moved:
            ghost = self._screen_point(self._drag.point) + self._drag.current - self._drag.start
            painter.setPen(QPen(QColor('#df7620'), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(ghost, 7, 7)
        painter.setPen(self.palette().text().color())
        plane = ''.join('XYZ'[i] for i in self.axes)
        painter.drawText(8, self.height() - 10, f'{plane}: перетащите оранжевую вершину · опоры закреплены')

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self.preview is None:
            self._cancel_drag()
            super().mousePressEvent(event)
            return
        self._cancel_drag()
        hits = self._point_hits(event.position())
        self._segment_start = event.position() if not hits else None
        if len(hits) > 1:
            self.ambiguousPick.emit()
        elif len(hits) == 1:
            code = hits[0]
            self.pointPicked.emit(code)
            if code.startswith('bend_'):
                point = next(p for key, p in self.points if key == code)
                _, _, scale = self._transform()
                self._drag = _Drag(code, point, event.position(), event.position(), scale,
                                   (self.width(), self.height()))
                self.dragStarted.emit(code)
                self.setFocus()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag.current = event.position()
            if (self._drag.current - self._drag.start).manhattanLength() >= 4:
                self._drag.moved = True
                delta = self._drag.current - self._drag.start
                candidate = list(self._drag.point)
                candidate[self.axes[0]] += delta.x() / self._drag.scale
                candidate[self.axes[1]] -= delta.y() / self._drag.scale
                self.dragMoved.emit(self._drag.code, tuple(candidate))
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        drag = self._drag
        start, self._segment_start = self._segment_start, None
        if event.button() == Qt.MouseButton.LeftButton and drag is None and start is not None and self.preview is not None:
            if (event.position() - start).manhattanLength() < 4:
                hits = straight_leg_hits(event.position(), self.preview.centerlines, self._screen_point)
                if len(hits) == 1:
                    self.segmentPicked.emit(*hits[0])
                elif len(hits) > 1:
                    self.ambiguousPick.emit()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or drag is None:
            super().mouseReleaseEvent(event)
            return
        self._drag = None
        self.update()
        if (drag.moved and drag.size == (self.width(), self.height()) and
                (event.position() - drag.start).manhattanLength() >= 4):
            delta = event.position() - drag.start
            candidate = list(drag.point)
            candidate[self.axes[0]] += delta.x() / drag.scale
            candidate[self.axes[1]] -= delta.y() / drag.scale
            self.dragReleased.emit(drag.code, self.axes, tuple(candidate))
        else:
            self.dragCancelled.emit()
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and (self._drag is not None or self._segment_start is not None):
            self._cancel_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._cancel_drag()
        super().hideEvent(event)
