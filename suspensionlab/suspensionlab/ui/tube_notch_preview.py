"""Изолированный предварительный просмотр подрезки выбранной пары."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from PySide6.QtCore import QLineF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.cad_transport import CadPreviewError
from ..core.cad_tube_notch_job import TubeNotchPreview, TubeNotchPreviewJob
from ..model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint
from ..model.cad_projection_layout import projection_layout


class NotchCanvas(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.result: TubeNotchPreview | None = None
        self.plane = 'XY'
        self.tube_only = False
        self.setMinimumSize(600, 250)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#ffffff'))
        result = self.result
        if result is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width() / 2
        index = ('XY', 'XZ', 'YZ').index(self.plane)
        before, after = ((result.tube_before, result.tube_after) if self.tube_only else
                         (result.before, result.after))
        mode = 'труба' if self.tube_only else 'пара'
        for panel, projection, title in ((0, before, 'До'), (1, after, 'После')):
            left = width * panel
            painter.setPen(QColor('#303840'))
            painter.drawText(QRectF(left + 4, 2, width - 8, 25), int(Qt.AlignmentFlag.AlignLeft),
                             f'{title}, {mode} — {self.plane}: +{self.plane[0]} →, +{self.plane[1]} ↑')
            frame = projection_layout(projection.bounds_mm, self.plane, width, float(self.height()))
            painter.save()
            painter.setClipRect(QRectF(left, 27, width, self.height() - 27))
            painter.setPen(QPen(QColor('#254b70'), 1.3))
            for x1, y1, x2, y2 in projection.views[index]:
                a, b = frame.screen(x1, y1), frame.screen(x2, y2)
                painter.drawLine(QLineF(left + a[0], a[1], left + b[0], b[1]))
            painter.restore()
        painter.end()


class _NotchReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], tube: str, housing: str, token: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.document, self.tube, self.housing, self.token = document, tube, housing, token
        self.job = TubeNotchPreviewJob()

    def run(self) -> None:
        try:
            self.completed.emit(self.token, self.job.run(self.document, self.tube, self.housing))
        except CadPreviewError as error:
            self.failed.emit(self.token, error.code)
        except Exception:
            self.failed.emit(self.token, 'unexpected')


class TubeNotchPreviewView(QWidget):
    def __init__(self, parent: QWidget, *, is_current: Callable[[dict[str, Any]], bool]) -> None:
        super().__init__(parent)
        self._is_current = is_current
        self._document: dict[str, Any] | None = None
        self._fingerprint: str | None = None
        self._pending: tuple[dict[str, Any], str, str] | None = None
        self._worker: _NotchReader | None = None
        self._closed = False
        self.generation = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._start)
        layout = QVBoxLayout(self)
        note = QLabel('Экспериментальная подрезка одной прямой трубы: корпус или другая труба режет '
                      'сплошным наружным цилиндром, пластина — собственным телом с отверстием. '
                      'Труба может остаться внутри отверстия пластины; проход крепежа не проверяется. '
                      'Показана только выбранная пара, режущая деталь не меняется. Нулевой зазор; '
                      'детали не продлеваются. Линии приближённые: пересечения могут отображаться неполно. '
                      'Это не проверка сварки, монтажа или прочности; сборка и .kim не меняются.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.tube = QComboBox(self)
        self.tube.addItem('Передняя труба', 'tube_front')
        self.tube.addItem('Задняя труба', 'tube_rear')
        form.addRow('Подрезаемая труба', self.tube)
        self.housing = QComboBox(self)
        self.housing.addItem('Передний корпус', 'housing_front')
        self.housing.addItem('Задний корпус', 'housing_rear')
        self.housing.addItem('Пластина у шаровой (если добавлена)', 'ball_plate')
        self.housing.addItem('Передняя труба (наружный цилиндр)', 'tube_front')
        self.housing.addItem('Задняя труба (наружный цилиндр)', 'tube_rear')
        form.addRow('Режущая деталь (не изменяется)', self.housing)
        self.plane = QComboBox(self)
        for plane in ('XY', 'XZ', 'YZ'):
            self.plane.addItem(plane, plane)
        form.addRow('Плоскость вида (общий масштаб до/после)', self.plane)
        layout.addLayout(form)
        self.only_tube = QCheckBox('Только подрезаемая труба (режущая деталь скрыта)')
        layout.addWidget(self.only_tube)
        self.enable = QCheckBox('Построить предварительную подрезку в фоне')
        layout.addWidget(self.enable)
        self.status = QLabel('Выключено. Для построения требуется CAD-ядро.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.canvas = NotchCanvas(self)
        layout.addWidget(self.canvas, 1)
        self.retry = QPushButton('Повторить построение')
        self.retry.setEnabled(False)
        layout.addWidget(self.retry)
        self.enable.toggled.connect(self._schedule)
        self.tube.currentIndexChanged.connect(self._schedule)
        self.housing.currentIndexChanged.connect(self._schedule)
        self.plane.currentIndexChanged.connect(self._change_plane)
        self.only_tube.toggled.connect(self._change_display)
        self.retry.clicked.connect(self._schedule)

    def _change_plane(self, *_args: object) -> None:
        self.canvas.plane = str(self.plane.currentData())
        self.canvas.update()
        self._display_status()

    def _change_display(self, enabled: bool) -> None:
        self.canvas.tube_only = enabled
        self.canvas.update()
        self._display_status()

    def _display_status(self) -> None:
        result = self.canvas.result
        if result is None:
            return
        before, after = ((result.tube_before, result.tube_after) if self.canvas.tube_only else
                         (result.before, result.after))
        mode = ('Показана только подрезаемая труба; режущая деталь скрыта.' if self.canvas.tube_only else
                'Показана пара деталей; режущая деталь может скрывать срез.')
        index = ('XY', 'XZ', 'YZ').index(self.canvas.plane)
        warning = (' На этой плоскости изменений не видно; попробуйте другую плоскость.'
                   if before.views[index] == after.views[index] else '')
        self.status.setText(f'{mode} До и после — в одном масштабе; при переключении режима масштаб может '
                            f'измениться. Ничего не применено и не сохранено; это не проверка геометрии '
                            f'для изготовления, сварки или прочности.{warning}')

    def set_document(self, document: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            code: str | None = assembly_snapshot_fingerprint(document)
        except (TypeError, ValueError, OverflowError, RecursionError):
            code = None
        if self._document == document and self._fingerprint == code:
            return
        self._document, self._fingerprint = deepcopy(document), code
        self._schedule()

    def _schedule(self, *_args: object) -> None:
        self.generation += 1
        self._timer.stop()
        self._pending = None
        self.canvas.result = None
        self.canvas.update()
        self.retry.setEnabled(False)
        if self._worker is not None:
            self._worker.job.cancel()
        if self._closed:
            self.status.setText('Остановка построения…')
        elif not self.enable.isChecked():
            self.status.setText('Выключено. Для построения требуется CAD-ядро.')
        elif self._document is None or self._fingerprint is None:
            self.status.setText('Снимок сборки недоступен или некорректен.')
        elif self.tube.currentData() == self.housing.currentData():
            self.status.setText('Выберите другую режущую деталь: нельзя подрезать трубу самой собой.')
        else:
            self._pending = (deepcopy(self._document), str(self.tube.currentData()), str(self.housing.currentData()))
            self.status.setText('Старый вид очищен. Подрезка строится по текущему снимку…')
            self._timer.start()

    def _start(self) -> None:
        if self._closed or self._worker is not None or self._pending is None:
            return
        document, tube, housing = self._pending
        self._pending = None
        worker = _NotchReader(document, tube, housing, self.generation, self)
        self._worker = worker
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    def _completed(self, token: int, result: object) -> None:
        if token != self.generation or self._closed or not self.enable.isChecked():
            return
        try:
            current = self._document is not None and self._is_current(self._document)
        except (TypeError, ValueError, OverflowError, RecursionError):
            current = False
        if not current:
            self._failed(token, 'changed')
            return
        if not isinstance(result, TubeNotchPreview):
            self._failed(token, 'output')
            return
        self.canvas.result = result
        self.canvas.update()
        self.retry.setEnabled(True)
        self._display_status()

    def _failed(self, token: int, code: str) -> None:
        if token != self.generation or self._closed:
            return
        reasons = {'no_overlap': 'труба и режущий объём выбранной детали не пересекаются',
                   'missing_plate': 'пластина не добавлена в сборку',
                   'same_tube': 'нельзя подрезать трубу самой собой',
                   'invalid_cutter': 'режущая деталь не прошла геометрическую проверку',
                   'empty_or_split': 'подрезка удаляет трубу или разделяет её на части',
                   'invalid_result': 'результат не прошёл геометрическую проверку',
                   'missing_cad': 'CAD-ядро недоступно', 'timeout': 'превышено время',
                   'cancelled': 'расчёт отменён', 'changed': 'снимок изменился',
                   'crash': 'CAD-процесс завершился аварийно', 'output': 'ошибка данных процесса'}
        self.canvas.result = None
        self.canvas.update()
        self.retry.setEnabled(self.enable.isChecked() and self._document is not None)
        self.status.setText(f'Предпросмотр не построен: {reasons.get(code, "ошибка CAD-построения")}. '
                            'Сборка и файлы не изменены.')

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
