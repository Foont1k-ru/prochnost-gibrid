"""Только чтение: попарный CAD-анализ независимого рычага."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.cad_fixed_arm_overlap_job import FixedArmOverlapJob, OverlapJobError, ProximityResult


class _ProximityReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], generation: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.document = document
        self.generation = generation
        self.job = FixedArmOverlapJob()

    def run(self) -> None:
        try:
            self.completed.emit(self.generation, self.job.run_proximity(self.document))
        except OverlapJobError as error:
            self.failed.emit(self.generation, str(error))
        except Exception:
            self.failed.emit(self.generation, 'unexpected')


class FreeArmProximity(QWidget):
    """Не изменяет документ и не предлагает автоматически резать детали."""

    def __init__(self, is_current: Callable[[dict[str, Any]], bool], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_current: Callable[[dict[str, Any]], bool] | None = is_current
        self._document: dict[str, Any] | None = None
        self._worker: _ProximityReader | None = None
        self._closed = False
        self.generation = 0
        layout = QVBoxLayout(self)
        title = QLabel('Расстояния и пересечения построенных CAD-деталей', self)
        title.setWordWrap(True)
        layout.addWidget(title)
        note = QLabel('Проверяются только текущие неподвижные CAD-тела после выбранных подрезок. '
                      'Расстояние — геометрический результат, не допуск и не проверка монтажа, движения, '
                      'сварки, прочности или безопасности. Малое расстояние не доказывает качество стыка. '
                      'Построение может занять время; параметры и файл не изменяются.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self._button = QPushButton('Проверить пары деталей', self)
        self._button.setObjectName('free_arm_proximity_start')
        self._button.setAutoDefault(False)
        self._button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._button.setEnabled(False)
        self._button.clicked.connect(self._start)
        layout.addWidget(self._button)
        self._cancel_button = QPushButton('Отменить проверку', self)
        self._cancel_button.setObjectName('free_arm_proximity_cancel')
        self._cancel_button.setAutoDefault(False)
        self._cancel_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self._cancel)
        layout.addWidget(self._cancel_button)
        self._status = QLabel('Примените параметры рычага, чтобы запустить проверку.', self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._table = QTableWidget(0, 5, self)
        self._table.setObjectName('free_arm_proximity_results')
        self._table.setMinimumHeight(220)
        self._table.setHorizontalHeaderLabels(['Пара деталей', 'Расстояние, мм', 'Общий объём, мм³',
                                               'Порог объёма, мм³', 'Результат'])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().hide()
        for index in range(5):
            self._table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        self._table.hide()
        layout.addWidget(self._table, 1)

    def _current(self) -> bool:
        return bool(not self._closed and self._document is not None and self._is_current is not None and
                    self._is_current(self._document))

    def set_document(self, document: dict[str, Any] | None) -> None:
        self.generation += 1
        self._document = deepcopy(document) if not self._closed else None
        if self._worker is not None:
            self._worker.job.cancel()
        self._clear_results()
        self._button.setEnabled(self._worker is None and self._current())
        self._cancel_button.setEnabled(False)
        self._status.setText('Параметры изменены; прежний результат скрыт. Примените ввод и запустите проверку.'
                             if document is None else
                             'Проверка текущих параметров ещё не запускалась. CAD строится отдельно.')

    def _clear_results(self) -> None:
        self._table.setRowCount(0)
        self._table.hide()

    def _start(self) -> None:
        if self._worker is not None or not self._current() or self._document is None:
            return
        self.generation += 1
        worker = _ProximityReader(deepcopy(self._document), self.generation, self)
        self._worker = worker
        self._clear_results()
        self._button.setEnabled(False)
        self._cancel_button.setEnabled(True)
        self._status.setText('Проверка выполняется в отдельном процессе; геометрия не изменяется…')
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    def _cancel(self) -> None:
        if self._worker is None:
            return
        self.generation += 1
        self._worker.job.cancel()
        self._cancel_button.setEnabled(False)
        self._clear_results()
        self._status.setText('Проверка отменена; достоверного результата нет.')

    def _completed(self, generation: int, result: object) -> None:
        if generation != self.generation or not self._current():
            return
        if not isinstance(result, ProximityResult):
            self._failed(generation, 'output')
            return
        names = {'tube_front': 'Передняя труба', 'tube_rear': 'Задняя труба',
                 'housing_front': 'Передний корпус', 'housing_rear': 'Задний корпус',
                 'ball_housing': 'Центральный корпус'}
        if not result.pairs or any(p.left not in names or p.right not in names for p in result.pairs):
            self._failed(generation, 'output')
            return
        labels = {'intersection': 'Пересечение', 'near': 'Касание или близость',
                  'uncertain_overlap': 'Малое пересечение: не определено',
                  'gap': 'Расстояние', 'error': 'Ошибка: не проверено'}
        self._table.setRowCount(len(result.pairs))
        for row, pair in enumerate(result.pairs):
            state = pair.status
            if state == 'intersection':
                distance = '— (пересечение)'
            elif state in ('error', 'uncertain_overlap') or pair.distance_mm is None:
                distance = '—'
            else:
                distance = f'{pair.distance_mm:.8g}'
            volume = '—' if pair.overlap_mm3 is None else f'{pair.overlap_mm3:.6g}'
            threshold = '—' if pair.threshold_mm3 is None else f'{pair.threshold_mm3:.3g}'
            for column, text in enumerate((f'{names[pair.left]} — {names[pair.right]}', distance,
                                           volume, threshold, labels[state])):
                self._table.setItem(row, column, QTableWidgetItem(text))
        failures = sum(p.status == 'error' for p in result.pairs)
        self._status.setText(f'Пар: {len(result.pairs)}; ошибок: {failures}. '
                             'Близость: не более 0,00001 мм; малый объём не даёт определённого вывода. '
                             'Это не проверка движения, монтажа, сварки или прочности.')
        self._table.show()

    def _failed(self, generation: int, code: str) -> None:
        if generation != self.generation or not self._current():
            return
        self._clear_results()
        reason = 'превышено время' if code == 'timeout' else 'не удалось построить или проверить детали'
        self._status.setText(f'Проверка не выполнена: {reason}. Достоверного результата нет.')

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._cancel_button.setEnabled(False)
        self._button.setEnabled(self._current())

    def shutdown(self) -> bool:
        if not self._closed:
            self._closed = True
            self.generation += 1
            self._document = None
            self._clear_results()
            self._button.setEnabled(False)
            self._cancel_button.setEnabled(False)
        if self._worker is not None:
            self._worker.job.cancel()
            if not self._worker.wait(3000):
                self._status.setText('Остановка проверки ещё продолжается. Попробуйте закрыть окно снова.')
                return False
        self._is_current = None  # break the bound callback cycle after successful shutdown
        return True
