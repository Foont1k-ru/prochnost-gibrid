"""Фоновая CAD-проекция с изоляцией, отменой и защитой от старых ответов."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import QLineF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.cad_assembly_projection_job import CadAssemblyProjection, CadAssemblyProjectionJob
from ..core.cad_transport import CadPreviewError
from ..model.cad_projection_layout import ProjectionLayout, format_reference_length, projection_layout


class ProjectionCanvas(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.projection: CadAssemblyProjection | None = None
        self.dimensions_enabled = True
        self.setMinimumSize(600, 280)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#ffffff'))
        projection = self.projection
        if projection is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width() / 3
        for index, (plane, title, lines) in enumerate(zip(
                ('XY', 'XZ', 'YZ'), ('XY: +X →, +Y ↑', 'XZ: +X →, +Z ↑', 'YZ: +Y →, +Z ↑'),
                projection.views, strict=True)):
            left = width * index
            painter.setPen(QColor('#303840'))
            painter.drawText(QRectF(left + 4, 2, width - 8, 25), int(Qt.AlignmentFlag.AlignLeft), title)
            frame = projection_layout(projection.bounds_mm, plane, width, float(self.height()))
            painter.save()
            painter.setClipRect(QRectF(left, 27, width, self.height() - 27))
            painter.setPen(QPen(QColor('#254b70'), 1.3))
            for x1, y1, x2, y2 in lines:
                a, b = frame.screen(x1, y1), frame.screen(x2, y2)
                painter.drawLine(QLineF(left + a[0], a[1], left + b[0], b[1]))
            if self.dimensions_enabled:
                self._draw_dimensions(painter, frame, left, width)
            painter.restore()
        painter.end()


    def set_dimensions_enabled(self, enabled: bool) -> None:
        self.dimensions_enabled = enabled
        self.update()

    def _draw_dimensions(self, painter: QPainter, frame: ProjectionLayout, left: float, width: float) -> None:
        """Показывает общие габариты CAD-тел, не размеры деталей или отверстий."""
        x1, ybottom = frame.screen(frame.u_min, frame.v_min)
        x2, ytop = frame.screen(frame.u_max, frame.v_max)
        x1, x2 = left + x1, left + x2
        dim_y, dim_x = ybottom + 13., x1 - 13.
        painter.setPen(QPen(QColor('#9b5016'), 1.0))
        # Extension lines end at the CAD bounding box, including hidden geometry.
        for x in (x1, x2):
            painter.drawLine(QLineF(x, ybottom + 2., x, dim_y + 3.))
        for y in (ytop, ybottom):
            painter.drawLine(QLineF(dim_x - 3., y, x1 - 2., y))
        painter.drawLine(QLineF(x1, dim_y, x2, dim_y))
        painter.drawLine(QLineF(dim_x, ytop, dim_x, ybottom))
        # Arrowheads, kept small enough for narrow projected spans.
        arrow_h = min(5., max(0., (x2 - x1) / 3.))
        arrow_v = min(5., max(0., (ybottom - ytop) / 3.))
        for dy in (-2., 2.):
            painter.drawLine(QLineF(x1, dim_y, x1 + arrow_h, dim_y + dy))
            painter.drawLine(QLineF(x2, dim_y, x2 - arrow_h, dim_y + dy))
        for dx in (-2., 2.):
            painter.drawLine(QLineF(dim_x, ytop, dim_x + dx, ytop + arrow_v))
            painter.drawLine(QLineF(dim_x, ybottom, dim_x + dx, ybottom - arrow_v))
        u_axis, v_axis = frame.plane[0], frame.plane[1]
        u_size, v_size = format_reference_length(frame.width_mm), format_reference_length(frame.height_mm)
        u_prefix, v_prefix = ('' if u_size.startswith('<') else '≈ '), ('' if v_size.startswith('<') else '≈ ')
        painter.drawText(QRectF(left + 2., dim_y + 3., width - 4., 19.),
                         int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                         f'{u_axis} {u_prefix}{u_size} мм')
        painter.save()
        painter.translate(dim_x - 7., (ytop + ybottom) / 2.)
        painter.rotate(-90.)
        painter.drawText(QRectF(-(self.height() - 50.) / 2., -10., self.height() - 50., 18.),
                         int(Qt.AlignmentFlag.AlignCenter), f'{v_axis} {v_prefix}{v_size} мм')
        painter.restore()


class _ProjectionReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], token: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.document, self.token = document, token
        self.job = CadAssemblyProjectionJob()

    def run(self) -> None:
        try:
            self.completed.emit(self.token, self.job.run(self.document))
        except CadPreviewError as error:
            self.failed.emit(self.token, error.code)
        except Exception:
            self.failed.emit(self.token, 'unexpected')


class CadAssemblyProjectionView(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._document: dict[str, Any] | None = None
        self._pending: dict[str, Any] | None = None
        self._worker: _ProjectionReader | None = None
        self._closed = False
        self.generation = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._start)
        layout = QVBoxLayout(self)
        note = QLabel('Видимые линии предварительных CAD-тел: две неподрезанные трубы, два корпуса и, '
                      'если добавлена, условная пластина. Кривые показаны ломаной; скрытые линии не выводятся. '
                      'Пересечения тел могут давать неполные или лишние линии. Это не производственный чертёж: '
                      'нет допусков, сварки, проверки монтажа и прочности. Масштаб видов различается.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.enable = QCheckBox('Построить предварительные CAD-проекции в фоне')
        self.enable.toggled.connect(self._schedule)
        layout.addWidget(self.enable)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setText('Выключено. Для построения требуется CAD-ядро.')
        layout.addWidget(self.status)
        self.canvas = ProjectionCanvas(self)
        layout.addWidget(self.canvas, 1)
        self.show_dimensions = QCheckBox('Размерные линии габаритов — справочно')
        self.show_dimensions.setChecked(True)
        self.show_dimensions.setToolTip('Границы всех предварительных CAD-тел, в том числе скрытых; '
                                        'не допуски и не размеры для изготовления.')
        self.show_dimensions.toggled.connect(self.canvas.set_dimensions_enabled)
        layout.addWidget(self.show_dimensions)
        self.bounds = QLabel()
        self.bounds.setWordWrap(True)
        self.bounds.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.bounds)
        self.retry = QPushButton('Повторить построение')
        self.retry.setEnabled(False)
        self.retry.clicked.connect(self._schedule)
        layout.addWidget(self.retry)

    def set_document(self, document: dict[str, Any]) -> None:
        if self._closed or self._document == document:
            return
        self._document = deepcopy(document)
        self._schedule()

    def _schedule(self, *_args: object) -> None:
        self.generation += 1
        self._timer.stop()
        self._pending = None
        self.canvas.projection = None
        self.canvas.update()
        self.bounds.clear()
        self.retry.setEnabled(False)
        if self._worker is not None:
            self._worker.job.cancel()
        if self._closed:
            self.status.setText('Остановка построения…')
        elif not self.enable.isChecked():
            self.status.setText('Выключено. Для построения требуется CAD-ядро.')
        elif self._document is not None:
            self._pending = deepcopy(self._document)
            self.status.setText('Старые проекции очищены. Фоновое построение по текущему снимку…')
            self._timer.start()

    def _start(self) -> None:
        if self._closed or self._worker is not None or self._pending is None:
            return
        document, self._pending = self._pending, None
        worker = _ProjectionReader(document, self.generation, self)
        self._worker = worker
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    def _completed(self, token: int, result: object) -> None:
        if token != self.generation or self._closed or not self.enable.isChecked():
            return
        if not isinstance(result, CadAssemblyProjection):
            self._failed(token, 'output')
            return
        self.canvas.projection = result
        self.canvas.update()
        bounds = result.bounds_mm
        rows = [f'{axis}: {format_reference_length(bounds[i + 3] - bounds[i])} '
                f'(от {bounds[i]:.1f} до {bounds[i + 3]:.1f})'
                for i, axis in enumerate(('X', 'Y', 'Z'))]
        self.bounds.setText('Справочные габариты CAD-тел, мм (в осях кузова; округление 0,1 мм):\n'
                            + '  •  '.join(rows) + '\nНе размеры для изготовления и не допуски.')
        self.retry.setEnabled(True)
        self.status.setText('Актуально для текущего снимка .kima. '
                            'Совпадение с текущим проектом проверяется отдельно ниже.')

    def _failed(self, token: int, code: str) -> None:
        if token != self.generation or self._closed:
            return
        reasons = {'missing_cad': 'CAD-ядро недоступно', 'timeout': 'превышено время',
                   'cancelled': 'построение отменено', 'limit': 'превышен предел сложности',
                   'no_shape': 'CAD-геометрия некорректна', 'coordinates': 'некорректные координаты',
                   'projection': 'не удалось вычислить видимые линии', 'output': 'некорректный ответ процесса',
                   'crash': 'CAD-процесс завершился аварийно', 'start': 'не удалось запустить процесс'}
        self.canvas.projection = None
        self.canvas.update()
        self.bounds.clear()
        self.retry.setEnabled(self.enable.isChecked() and self._document is not None)
        self.status.setText(f'Проекции не построены: {reasons.get(code, "ошибка построения")}. '
                            'Сборка не изменена; условные виды доступны отдельно.')

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        if self._pending is not None and not self._closed:
            self._timer.start()

    def shutdown(self) -> bool:
        if not self._closed:
            self._closed = True
            self._schedule()
        if self._worker is None:
            return True
        self._worker.job.cancel()
        return bool(self._worker.wait(3000))
