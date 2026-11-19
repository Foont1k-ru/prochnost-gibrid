"""Предварительный просмотр последовательности резов, без изменения сборки."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.cad_transport import CadPreviewError
from ..core.cad_tube_notch_job import TubeNotchPreview
from ..core.cad_tube_notch_sequence_job import SequencePreview, SequencePreviewError, SequencePreviewJob
from ..model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint
from .tube_notch_preview import NotchCanvas

CUTTER_LABELS = {
    'housing_front': 'Передний корпус',
    'housing_rear': 'Задний корпус',
    'ball_plate': 'Пластина у шаровой',
    'tube_front': 'Передняя труба (наружный цилиндр)',
    'tube_rear': 'Задняя труба (наружный цилиндр)',
}


class _SequenceReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str, object)

    def __init__(self, document: dict[str, Any], tube: str, cutters: tuple[str, ...],
                 token: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.document, self.tube, self.cutters, self.token = document, tube, cutters, token
        self.job = SequencePreviewJob()

    def run(self) -> None:
        try:
            self.completed.emit(self.token, self.job.run(self.document, self.tube, self.cutters))
        except SequencePreviewError as error:
            self.failed.emit(self.token, error.code, (error.step_index, error.cutter_id))
        except CadPreviewError as error:
            self.failed.emit(self.token, error.code, None)
        except Exception:
            self.failed.emit(self.token, 'unexpected', None)


class TubeNotchSequencePreviewView(QWidget):
    def __init__(self, parent: QWidget, *, is_current: Callable[[dict[str, Any]], bool]) -> None:
        super().__init__(parent)
        self._is_current = is_current
        self._document: dict[str, Any] | None = None
        self._fingerprint: str | None = None
        self._pending: tuple[dict[str, Any], str, tuple[str, ...]] | None = None
        self._worker: _SequenceReader | None = None
        self._closed = False
        self.generation = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._start)

        layout = QVBoxLayout(self)
        note = QLabel('Экспериментальный просмотр одной трубы до и после всех отмеченных резов. '
                      'Режущие детали берутся из исходной сборки и не показаны; порядок — сверху вниз. '
                      'Корпуса и другая труба режут наружным конечным цилиндром, пластина — телом '
                      'с отверстием (труба может остаться в отверстии). Нулевой зазор, без продления. '
                      'Это не проверка монтажа, сварки или прочности; ничего не применяется и не сохраняется.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.tube = QComboBox(self)
        self.tube.addItem('Передняя труба', 'tube_front')
        self.tube.addItem('Задняя труба', 'tube_rear')
        form.addRow('Подрезаемая труба', self.tube)
        self.plane = QComboBox(self)
        for plane in ('XY', 'XZ', 'YZ'):
            self.plane.addItem(plane, plane)
        form.addRow('Плоскость вида (одинаковый масштаб до/после)', self.plane)
        layout.addLayout(form)
        layout.addWidget(QLabel('Отметьте режущие детали; изменяйте порядок кнопками:'))
        row = QHBoxLayout()
        self.cutters = QListWidget(self)
        self.cutters.setMinimumHeight(120)
        for code, label in CUTTER_LABELS.items():
            item = QListWidgetItem(label, self.cutters)
            item.setData(Qt.ItemDataRole.UserRole, code)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        row.addWidget(self.cutters, 1)
        buttons = QVBoxLayout()
        self.up = QPushButton('Выше', self)
        self.down = QPushButton('Ниже', self)
        buttons.addWidget(self.up)
        buttons.addWidget(self.down)
        buttons.addStretch(1)
        row.addLayout(buttons)
        layout.addLayout(row)
        self.enable = QCheckBox('Построить последовательность в фоне')
        layout.addWidget(self.enable)
        self.status = QLabel('Выключено. Для построения требуется CAD-ядро.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.canvas = NotchCanvas(self)
        self.canvas.tube_only = True
        layout.addWidget(self.canvas, 1)
        self.retry = QPushButton('Повторить построение')
        self.retry.setEnabled(False)
        layout.addWidget(self.retry)
        self.cutters.itemChanged.connect(self._schedule)
        self.tube.currentIndexChanged.connect(self._schedule)
        self.enable.toggled.connect(self._schedule)
        self.plane.currentIndexChanged.connect(self._change_plane)
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))
        self.retry.clicked.connect(self._schedule)

    def _order(self) -> tuple[str, ...]:
        return tuple(str(self.cutters.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.cutters.count())
                     if self.cutters.item(i).checkState() == Qt.CheckState.Checked)

    def _move(self, delta: int) -> None:
        row = self.cutters.currentRow()
        destination = row + delta
        if row < 0 or not 0 <= destination < self.cutters.count():
            return
        item = self.cutters.takeItem(row)
        self.cutters.insertItem(destination, item)
        self.cutters.setCurrentRow(destination)
        self._schedule()

    def _change_plane(self, *_args: object) -> None:
        self.canvas.plane = str(self.plane.currentData())
        self.canvas.update()
        self._display_status()

    def _display_status(self) -> None:
        result = self.canvas.result
        if result is None:
            return
        index = ('XY', 'XZ', 'YZ').index(self.canvas.plane)
        warning = (' На этой плоскости изменений не видно; попробуйте другую плоскость.'
                   if result.before.views[index] == result.after.views[index] else '')
        self.status.setText('Показана только выбранная труба до и после всех резов; режущие детали скрыты. '
                            'Линии приближённые, часть геометрии может быть скрыта. '
                            'Ничего не применено и не сохранено.' + warning)

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
        elif not self._order():
            self.status.setText('Отметьте хотя бы одну режущую деталь; порядок — сверху вниз.')
        else:
            self._pending = (deepcopy(self._document), str(self.tube.currentData()), self._order())
            self.status.setText('Старый вид очищен. Строится последовательность резов…')
            self._timer.start()

    def _start(self) -> None:
        if self._closed or self._worker is not None or self._pending is None:
            return
        document, tube, cutters = self._pending
        self._pending = None
        worker = _SequenceReader(document, tube, cutters, self.generation, self)
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
            self._failed(token, 'changed', None)
            return
        if not isinstance(result, SequencePreview):
            self._failed(token, 'output', None)
            return
        # Reuse the tube-only canvas, with the same bounds for both states.
        self.canvas.result = TubeNotchPreview(result.before, result.after, result.before, result.after)
        self.canvas.update()
        self.retry.setEnabled(True)
        self._display_status()

    def _failed(self, token: int, code: str, step: object) -> None:
        if token != self.generation or self._closed:
            return
        reasons = {'no_overlap': 'на этом шаге нет существенного пересечения',
                   'empty_or_split': 'рез удаляет трубу или разделяет её на части',
                   'missing_plate': 'пластина не добавлена в сборку',
                   'same_tube': 'труба не может подрезать саму себя',
                   'invalid_result': 'результат не прошёл геометрическую проверку',
                   'missing_cad': 'CAD-ядро недоступно', 'timeout': 'превышено время',
                   'cancelled': 'расчёт отменён', 'changed': 'снимок изменился',
                   'crash': 'CAD-процесс завершился аварийно', 'output': 'ошибка данных процесса'}
        context = ''
        order = self._order()
        if (isinstance(step, tuple) and len(step) == 2 and type(step[0]) is int and
                0 <= step[0] < len(order) and step[1] == order[step[0]]):
            context = f' Шаг {step[0] + 1} — {CUTTER_LABELS[order[step[0]]]}. '
        self.canvas.result = None
        self.canvas.update()
        self.retry.setEnabled(self.enable.isChecked() and bool(order) and self._document is not None)
        self.status.setText(f'Последовательность не построена.{context} '
                            f'{reasons.get(code, "ошибка CAD-построения")}. '
                            'Частичный результат не показан; сборка и файлы не изменены.')

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
