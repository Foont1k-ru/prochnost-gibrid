"""Изолированная проверка пересечений и расстояний деталей снимка."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.cad_fixed_arm_overlap_job import (
    FixedArmOverlapJob,
    OverlapJobError,
    OverlapResult,
    PairwiseResult,
    ProximityResult,
)


class _OverlapReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], token: int, parent: QWidget, *,
                 all_parts: bool = False, proximity: bool = False) -> None:
        super().__init__(parent)
        self.document = document
        self.token = token
        self.all_parts = all_parts
        self.proximity = proximity
        self.job = FixedArmOverlapJob()

    def run(self) -> None:
        try:
            result: ProximityResult | PairwiseResult | OverlapResult
            if self.proximity:
                result = self.job.run_proximity(self.document)
            elif self.all_parts:
                result = self.job.run_all(self.document)
            else:
                result = self.job.run(self.document)
            self.completed.emit(self.token, result)
        except OverlapJobError as error:
            self.failed.emit(self.token, str(error))
        except Exception:
            self.failed.emit(self.token, 'unexpected')


class FixedArmOverlap(QWidget):
    def __init__(self, is_current: Callable[[dict[str, Any]], bool], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_current = is_current
        self._document: dict[str, Any] | None = None
        self._worker: _OverlapReader | None = None
        self._closed = False
        self.generation = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        self._button = QPushButton('Проверить пересечение двух труб', self)
        self._button.setEnabled(False)
        self._button.clicked.connect(self._start)
        actions.addWidget(self._button)
        self._all_button = QPushButton('Проверить все пары деталей', self)
        self._all_button.setEnabled(False)
        self._all_button.clicked.connect(self._start_all)
        actions.addWidget(self._all_button)
        layout.addLayout(actions)
        self._distance_button = QPushButton('Расстояния и пересечения всех пар', self)
        self._distance_button.setEnabled(False)
        self._distance_button.clicked.connect(self._start_proximity)
        layout.addWidget(self._distance_button)
        self._status = QLabel('Проверка не запускалась. Касание, зазоры и прочность не определяются.', self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(['Пара', 'Объём, мм³', 'Порог, мм³', 'Результат'])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in (1, 2, 3):
            self._table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().hide()
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setMinimumHeight(180)
        self._table.setMaximumHeight(260)
        self._table.hide()
        layout.addWidget(self._table)

    def set_document(self, document: dict[str, Any] | None) -> None:
        self.generation += 1
        self._document = document
        if self._worker is not None:
            self._worker.job.cancel()
        enabled = not self._closed and document is not None and self._worker is None
        self._button.setEnabled(enabled)
        self._all_button.setEnabled(enabled)
        self._distance_button.setEnabled(enabled)
        self._table.setRowCount(0)
        self._table.hide()
        self._status.setText('Проверка не запускалась для текущих параметров. '
                             'Касание, зазоры и прочность не определяются.')

    def _start(self) -> None:
        self._run_check(all_parts=False)

    def _start_all(self) -> None:
        self._run_check(all_parts=True)

    def _start_proximity(self) -> None:
        self._run_check(all_parts=False, proximity=True)

    def _run_check(self, *, all_parts: bool, proximity: bool = False) -> None:
        if self._closed or self._worker is not None or self._document is None:
            return
        if not self._is_current(self._document):
            self._table.setRowCount(0)
            self._table.hide()
            self._status.setText('Снимок устарел; повторите фиксацию и проверку.')
            return
        worker = _OverlapReader(self._document, self.generation, self, all_parts=all_parts, proximity=proximity)
        self._worker = worker
        self._button.setEnabled(False)
        self._all_button.setEnabled(False)
        self._distance_button.setEnabled(False)
        self._table.setRowCount(0)
        self._table.hide()
        if proximity:
            text = 'Проверка расстояний и пересечений выполняется в отдельном процессе…'
        elif all_parts:
            text = 'Проверка всех пар деталей выполняется в отдельном процессе…'
        else:
            text = 'Проверка двух труб выполняется в отдельном процессе…'
        self._status.setText(text)
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    def _completed(self, token: int, result: object) -> None:
        if token != self.generation or self._closed or self._document is None:
            return
        if not self._is_current(self._document):
            self._table.setRowCount(0)
            self._table.hide()
            self._status.setText('Снимок устарел; результат скрыт.')
            return
        if isinstance(result, ProximityResult):
            self._show_proximity(result)
            return
        if isinstance(result, PairwiseResult):
            self._show_pairs(result)
            return
        if not isinstance(result, OverlapResult):
            self._failed(token, 'output')
            return
        if result.overlap_mm3 > result.threshold_mm3:
            finding = f'Обнаружено объёмное пересечение труб: примерно {result.overlap_mm3:.6g} мм³.'
        else:
            finding = (f'Объёмного пересечения выше численного порога {result.threshold_mm3:.3g} мм³ '
                       'не обнаружено.')
        self._status.setText(finding + ' Это не проверка касания, минимального зазора, сварки или прочности; '
                             'корпуса и другие детали не проверяются.')

    def _show_pairs(self, result: PairwiseResult) -> None:
        names = {'tube_front': 'Передняя труба', 'tube_rear': 'Задняя труба',
                 'housing_front': 'Передний корпус', 'housing_rear': 'Задний корпус'}
        if not result.pairs or any(pair.left not in names or pair.right not in names for pair in result.pairs):
            self._failed(self.generation, 'output')
            return
        count = sum(pair.overlap_mm3 > pair.threshold_mm3 for pair in result.pairs)
        self._status.setText(f'Проверено пар: {len(result.pairs)}; объём выше численного порога: {count}. '
                             'Ниже порога не означает наличие зазора: касание, расстояния, сварка и прочность '
                             'не проверяются. Таблицу можно прокручивать.')
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(['Пара', 'Объём, мм³', 'Порог, мм³', 'Результат'])
        self._table.setRowCount(len(result.pairs))
        for row, pair in enumerate(result.pairs):
            status = 'Есть объём' if pair.overlap_mm3 > pair.threshold_mm3 else 'Ниже порога'
            cells = (f'{names[pair.left]} — {names[pair.right]}', f'{pair.overlap_mm3:.6g}',
                     f'{pair.threshold_mm3:.3g}', status)
            for column, text in enumerate(cells):
                self._table.setItem(row, column, QTableWidgetItem(text))
        self._table.show()

    def _show_proximity(self, result: ProximityResult) -> None:
        names = {'tube_front': 'Передняя труба', 'tube_rear': 'Задняя труба',
                 'housing_front': 'Передний корпус', 'housing_rear': 'Задний корпус'}
        if not result.pairs or any(pair.left not in names or pair.right not in names for pair in result.pairs):
            self._failed(self.generation, 'output')
            return
        counts = {status: sum(pair.status == status for pair in result.pairs)
                  for status in ('intersection', 'near', 'uncertain_overlap', 'gap', 'error')}
        self._status.setText(
            f'Пар: {len(result.pairs)}; пересечение: {counts["intersection"]}; '
            f'касание или ближе допуска: {counts["near"]}; малый объём ниже порога: {counts["uncertain_overlap"]}; '
            f'зазор: {counts["gap"]}; ошибок: {counts["error"]}. '
            'Допуск расстояния 0,00001 мм. Только текущие CAD-тела после подрезок; '
            'не проверка движения, сварки, монтажа или прочности. Таблицу можно прокручивать.')
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(['Пара', 'Расстояние, мм', 'Объём, мм³', 'Порог, мм³', 'Результат'])
        for index in (1, 2, 3, 4):
            self._table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setRowCount(len(result.pairs))
        labels = {'intersection': 'Пересечение', 'near': 'Касание / в допуске',
                  'uncertain_overlap': 'Возможное малое пересечение', 'gap': 'Зазор', 'error': 'Ошибка — не проверено'}
        for row, pair in enumerate(result.pairs):
            state = pair.status
            if state == 'intersection':
                distance = '0 (пересечение)'
            elif state in ('error', 'uncertain_overlap'):
                distance = '—'
            else:
                assert pair.distance_mm is not None
                distance = f'{pair.distance_mm:.8g}'
            volume = '—' if pair.overlap_mm3 is None else f'{pair.overlap_mm3:.6g}'
            threshold = '—' if pair.threshold_mm3 is None else f'{pair.threshold_mm3:.3g}'
            cells = (f'{names[pair.left]} — {names[pair.right]}', distance, volume, threshold, labels[state])
            for column, text in enumerate(cells):
                self._table.setItem(row, column, QTableWidgetItem(text))
        self._table.show()

    def _failed(self, token: int, code: str) -> None:
        if token != self.generation or self._closed:
            return
        self._table.setRowCount(0)
        self._table.hide()
        if self._document is None or not self._is_current(self._document):
            self._status.setText('Снимок устарел; результат скрыт.')
            return
        reason = 'превышено время' if code == 'timeout' else 'не удалось построить или проверить детали'
        self._status.setText(f'Проверка не выполнена: {reason}. Достоверного результата нет.')

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        enabled = not self._closed and self._document is not None
        self._button.setEnabled(enabled)
        self._all_button.setEnabled(enabled)
        self._distance_button.setEnabled(enabled)

    def shutdown(self) -> bool:
        self._closed = True
        self.generation += 1
        self._document = None
        self._button.setEnabled(False)
        self._all_button.setEnabled(False)
        self._distance_button.setEnabled(False)
        self._table.setRowCount(0)
        self._table.hide()
        if self._worker is None:
            return True
        self._worker.job.cancel()
        return bool(self._worker.wait(3000))
