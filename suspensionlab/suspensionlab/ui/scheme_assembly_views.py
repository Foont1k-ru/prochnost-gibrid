"""Фоновые условные виды снимка сборки; CAD-тела здесь не строятся."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from copy import deepcopy
from typing import Any
from weakref import ref

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from ..model.scheme_assembly_views import AssemblyViews, assembly_views

# Only pure, bounded Python calculations are run here: no Qt or OCCT in workers.
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='assembly-views')


class ViewsCanvas(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.views: AssemblyViews | None = None
        self.setMinimumHeight(210)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#ffffff'))
        views = self.views
        if views is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width() / 3
        for index, plane in enumerate(('XY', 'XZ', 'YZ')):
            x = width * index
            painter.setPen(QColor('#303840'))
            painter.drawText(QRectF(x + 6, 2, width - 12, 24), int(Qt.AlignmentFlag.AlignLeft), plane)
            lines = views.project(plane)
            points = [point for a, b, _kind in lines for point in (a, b)]
            if not points:
                continue
            xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
            ymin, ymax = min(p[1] for p in points), max(p[1] for p in points)
            available_w, available_h = max(1., width - 24), max(1., self.height() - 52.)
            scale = min(available_w / max(xmax - xmin, 1.), available_h / max(ymax - ymin, 1.))
            cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
            def screen(point: tuple[float, float], x: float = x, cx: float = cx, cy: float = cy,
                       scale: float = scale, available_h: float = available_h) -> QPointF:
                return QPointF(x + width / 2 + (point[0] - cx) * scale,
                               28 + available_h / 2 - (point[1] - cy) * scale)
            for a, b, kind in lines:
                pen = QPen(QColor({'tube': '#1b5b9a', 'housing': '#c55b19',
                                   'plate': '#27805a', 'hole': '#27805a'}[kind]), 2)
                if kind in ('tube', 'housing'):
                    pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(screen(a), screen(b))
        painter.end()


class SchemeAssemblyViews(QWidget):
    _delivered = Signal(int, object)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._document: dict[str, Any] | None = None
        self._pending: dict[str, Any] | None = None
        self._future: Future[AssemblyViews] | None = None
        self._closed = False
        self.generation = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._start)
        self._delivered.connect(self._completed)
        layout = QVBoxLayout(self)
        note = QLabel('Условные ортографические виды снимка .kima: пунктир — оси труб и корпусов; '
                      'зелёный — средняя плоскость пластины и приближённая окружность отверстия. '
                      'Толщина и наружные контуры тел, скрытые линии, подрезки и сварка не показаны. '
                      'Не CAD-проекция, не габариты и не производственный чертёж.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.canvas = ViewsCanvas(self)
        layout.addWidget(self.canvas, 1)
        self.dimensions = QPlainTextEdit(self)
        self.dimensions.setReadOnly(True)
        self.dimensions.setAccessibleName('Справочные размеры')
        layout.addWidget(self.dimensions, 1)

    def set_document(self, document: dict[str, Any]) -> None:
        if self._closed or self._document == document:
            return
        self._document = deepcopy(document)
        self._pending = deepcopy(document)
        self.generation += 1
        self.canvas.views = None
        self.canvas.update()
        self.dimensions.clear()
        self.status.setText('Виды устарели: фоновое построение по текущему снимку сборки…')
        self._timer.start()

    def _start(self) -> None:
        if self._closed or self._future is not None or self._pending is None:
            return
        document, self._pending = self._pending, None
        token = self.generation
        future = _EXECUTOR.submit(assembly_views, document)
        self._future = future
        owner = ref(self)
        def deliver(done: Future[AssemblyViews]) -> None:
            try:
                result: object = done.result()
            except Exception:
                result = None
            widget = owner()
            if widget is not None:
                # The C++ widget may have been deleted before completion.
                with suppress(RuntimeError):
                    widget._delivered.emit(token, result)
        future.add_done_callback(deliver)

    def _completed(self, token: int, result: object) -> None:
        self._future = None
        if self._closed:
            return
        if token == self.generation:
            if isinstance(result, AssemblyViews):
                self.canvas.views = result
                self.canvas.update()
                self.dimensions.setPlainText('Справочно, мм (без допусков и подрезок):\n' + '\n'.join(
                    f'{d.label}: {d.value_mm:.2f}' for d in result.dimensions))
                self.status.setText('Актуально для текущего снимка сборки. '
                                    'Совпадение с проектом проверяется отдельно ниже.')
            else:
                self.status.setText('Не удалось построить виды. Данные сборки не изменены.')
        if self._pending is not None:
            self._timer.start()

    def shutdown(self) -> None:
        self._closed = True
        self.generation += 1
        self._timer.stop()
        self._pending = None
        if self._future is not None:
            self._future.cancel()
