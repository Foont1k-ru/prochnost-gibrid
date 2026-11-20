"""Изолированная проверка пересечений и расстояний деталей снимка."""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.cad_fixed_arm_overlap_job import (
    DISTANCE_TOLERANCE_MM,
    FixedArmOverlapJob,
    OverlapJobError,
    OverlapResult,
    PairwiseResult,
    ProximityResult,
    SuggestionResult,
)


class _OverlapReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], token: int, parent: QWidget, *,
                 all_parts: bool = False, proximity: bool = False,
                 suggestion: tuple[str, str, float] | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.token = token
        self.all_parts = all_parts
        self.proximity = proximity
        self.suggestion = suggestion
        self.job = FixedArmOverlapJob()

    def run(self) -> None:
        try:
            result: ProximityResult | PairwiseResult | OverlapResult | SuggestionResult
            if self.suggestion is not None:
                result = self.job.run_suggestion(self.document, *self.suggestion)
            elif self.proximity:
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
    markersRequested = Signal(object)

    def __init__(self, is_current: Callable[[dict[str, Any]], bool], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_current = is_current
        self._document: dict[str, Any] | None = None
        self._worker: _OverlapReader | None = None
        self._proximity: ProximityResult | None = None
        self._requirement_pair: tuple[str, str] | None = None
        self._suggestion: SuggestionResult | None = None
        self._apply_callback: Callable[[dict[str, Any], SuggestionResult], None] | None = None
        self._closed = False
        self.generation = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        navigation = QLabel('Для подбора: рассчитайте расстояния, выберите пару и прокрутите вниз.', self)
        navigation.setWordWrap(True)
        layout.addWidget(navigation)
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
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.itemSelectionChanged.connect(self._requirement_changed)
        layout.addWidget(self._table)
        hint = QLabel('Выберите строку расстояний: в актуальном CAD показывается одна пара ближайших точек. '
                      'Задайте минимум для этой пары. Подбор проверяет только поддержанные резы; '
                      'ничего не применяется автоматически.', self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self._minimum = QLineEdit(self)
        self._minimum.setPlaceholderText('Минимальный зазор выбранной пары, мм')
        self._minimum.setMaxLength(32)
        self._minimum.textChanged.connect(self._requirement_changed)
        row.addWidget(self._minimum)
        self._suggest_button = QPushButton('Подобрать подрезку', self)
        self._suggest_button.setEnabled(False)
        self._suggest_button.clicked.connect(self._start_suggestion)
        row.addWidget(self._suggest_button)
        layout.addLayout(row)
        self._suggest_status = QLabel('Требуемый зазор не задан; проверка требования не выполнена.', self)
        self._suggest_status.setWordWrap(True)
        layout.addWidget(self._suggest_status)
        self._apply_button = QPushButton('Применить предложение…', self)
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._confirm_suggestion)
        layout.addWidget(self._apply_button)

    def set_apply_callback(self, callback: Callable[[dict[str, Any], SuggestionResult], None]) -> None:
        self._apply_callback = callback

    def set_document(self, document: dict[str, Any] | None) -> None:
        self.generation += 1
        self._document = document
        self.markersRequested.emit(())
        self._proximity = None
        self._requirement_pair = None
        self._suggestion = None
        self._minimum.clear()
        self._suggest_button.setEnabled(False)
        self._apply_button.setEnabled(False)
        self._suggest_status.setText('Требуемый зазор не задан; проверка требования не выполнена.')
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

    def _requirement_changed(self, *_args: object) -> None:
        self._suggestion = None
        self._apply_button.setEnabled(False)
        row = self._table.currentRow()
        pair = self._proximity.pairs[row] if self._proximity is not None and 0 <= row < len(self._proximity.pairs) else None
        key = (pair.left, pair.right) if pair is not None else None
        if key != self._requirement_pair:
            self._requirement_pair = key
            self._minimum.blockSignals(True)
            self._minimum.clear()
            self._minimum.blockSignals(False)
        value = self._minimum_value()
        points = pair.points if pair is not None and pair.status == 'gap' and pair.points is not None else ()
        self.markersRequested.emit(points)
        self._suggest_button.setEnabled(not self._closed and self._worker is None and value is not None and pair is not None)
        if value is None or pair is None:
            self._suggest_status.setText('Выберите пару и явно задайте 0 или минимум больше 0,00001 и не более 100 мм. '
                                         '0 допускает касание. Для остальных пар требование не задано.')
            return
        if pair.status in ('error', 'uncertain_overlap'):
            state = 'не проверено'
        elif pair.status == 'intersection':
            state = 'не выполнено: пересечение'
        elif value == 0 and pair.status in ('near', 'gap'):
            state = 'нет рассчитанного объёмного пересечения; касание допускается'
        elif pair.status == 'near' or pair.distance_mm is None or pair.distance_mm < value:
            state = 'не выполнено: расстояние меньше минимума или в допуске'
        elif pair.distance_mm < value + DISTANCE_TOLERANCE_MM:
            state = 'у границы: численно не подтверждено'
        else:
            state = 'выполнено для этого снимка'
        self._suggest_status.setText(f'Выбранная пара: требование {value:g} мм — {state}. '
                                     'Для остальных пар требование не задано. '
                                     'При доступном CAD показывается одна пара ближайших точек.')

    def _minimum_value(self) -> float | None:
        try:
            value = float(self._minimum.text().strip().replace(',', '.'))
            return value if math.isfinite(value) and (value == 0 or DISTANCE_TOLERANCE_MM < value <= 100) else None
        except ValueError:
            return None

    def _start_suggestion(self) -> None:
        value, row = self._minimum_value(), self._table.currentRow()
        if self._proximity is None or value is None or not 0 <= row < len(self._proximity.pairs):
            return
        pair = self._proximity.pairs[row]
        self._run_check(all_parts=False, suggestion=(pair.left, pair.right, value))

    def _confirm_suggestion(self) -> None:
        candidate, doc, token = self._suggestion, self._document, self.generation
        if candidate is None or doc is None or self._apply_callback is None or not self._is_current(doc):
            return
        if candidate.radial_clearance_mm is None:
            return
        kind = 'по другой трубе' if candidate.kind == 'joint' else 'по своему корпусу'
        target = 'переднюю' if candidate.target == 'front' else 'заднюю'
        text = (f'Применить проверенный вариант: подрезать {target} трубу {kind}, '
                f'радиальный размер реза {candidate.radial_clearance_mm:g} мм?\n'
                'Другие зазоры, сварка, прочность и движение не удостоверены.')
        answer = QMessageBox.question(self, 'Применить подрезку?', text,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if (answer == QMessageBox.StandardButton.Yes and token == self.generation and
                self._suggestion is candidate and self._document is doc and self._is_current(doc)):
            self._apply_callback(doc, candidate)

    def _start(self) -> None:
        self._run_check(all_parts=False)

    def _start_all(self) -> None:
        self._run_check(all_parts=True)

    def _start_proximity(self) -> None:
        self._run_check(all_parts=False, proximity=True)

    def _run_check(self, *, all_parts: bool, proximity: bool = False,
                   suggestion: tuple[str, str, float] | None = None) -> None:
        if self._closed or self._worker is not None or self._document is None:
            return
        if not self._is_current(self._document):
            self._table.setRowCount(0)
            self._table.hide()
            self._status.setText('Снимок устарел; повторите фиксацию и проверку.')
            return
        worker = _OverlapReader(self._document, self.generation, self, all_parts=all_parts,
                                proximity=proximity, suggestion=suggestion)
        self._worker = worker
        self._button.setEnabled(False)
        self._all_button.setEnabled(False)
        self._distance_button.setEnabled(False)
        self._suggest_button.setEnabled(False)
        self._apply_button.setEnabled(False)
        self._table.setEnabled(False)
        self._minimum.setEnabled(False)
        if suggestion is None:
            self._proximity = None
            self._table.setRowCount(0)
            self._table.hide()
        if suggestion is not None:
            text = 'Подбор и проверка вариантов выполняются в отдельном процессе…'
        elif proximity:
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
        if isinstance(result, SuggestionResult):
            self._show_suggestion(result)
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

    def _show_suggestion(self, result: SuggestionResult) -> None:
        self._suggestion = result if result.outcome == 'candidate' else None
        messages = {'already': 'На текущем снимке выбранный минимум уже выполнен; рез не предлагается.',
                    'unverified': 'Некоторые пары или варианты не рассчитаны либо неоднозначны; '
                                  'подтверждённый вариант не найден.',
                    'no_candidate': 'Среди ограниченного набора поддержанных резов подходящий вариант не найден. '
                                    'Это не доказывает отсутствие других решений.'}
        if result.outcome != 'candidate':
            self._suggest_status.setText(messages.get(result.outcome, 'Неизвестный результат; не проверено.'))
            self._status.setText('Подбор завершён без предложения. Проверьте исходный отчёт.')
            return
        assert result.after is not None and result.radial_clearance_mm is not None
        row = self._table.currentRow()
        if self._proximity is None or not 0 <= row < len(self._proximity.pairs):
            self._suggestion = None
            return
        pair = self._proximity.pairs[row]
        after = next((p for p in result.after.pairs if (p.left, p.right) == (pair.left, pair.right)), None)
        if after is None or after.distance_mm is None:
            self._suggestion = None
            return
        labels = {'joint': 'по другой трубе', 'housing': 'по своему корпусу'}
        target = 'переднюю' if result.target == 'front' else 'заднюю'
        conflicts = sum(p.status == 'intersection' for p in result.after.pairs)
        self._suggest_status.setText(f'Предложение: подрезать {target} трубу {labels[result.kind or ""]}; '
                                     f'радиальный размер реза {result.radial_clearance_mm:g} мм. '
                                     f'Расчётный зазор выбранной пары {after.distance_mm:.6g} мм; '
                                     f'пересечений среди всех пар после реза: {conflicts}. '
                                     'Другие зазоры и пригодность конструкции не удостоверены.')
        self._status.setText('Предложение не применено. Проверены только рассчитанные CAD-тела и ограниченный набор резов.')
        self._apply_button.setEnabled(self._worker is None and self._apply_callback is not None)

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
        self._proximity = result
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
        self._table.selectRow(0)
        self._requirement_changed()

    def _failed(self, token: int, code: str) -> None:
        if token != self.generation or self._closed:
            return
        self._proximity = None
        self._suggestion = None
        self._suggest_button.setEnabled(False)
        self._apply_button.setEnabled(False)
        self._suggest_status.setText('Проверка требования и подбор не выполнены.')
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
        self._table.setEnabled(enabled)
        self._minimum.setEnabled(enabled)
        row = self._table.currentRow()
        self._suggest_button.setEnabled(enabled and self._minimum_value() is not None and
                                       self._proximity is not None and 0 <= row < len(self._proximity.pairs))
        self._apply_button.setEnabled(enabled and self._suggestion is not None and self._apply_callback is not None)

    def shutdown(self) -> bool:
        self._closed = True
        self.generation += 1
        self._document = None
        self._button.setEnabled(False)
        self._all_button.setEnabled(False)
        self._distance_button.setEnabled(False)
        self._suggest_button.setEnabled(False)
        self._apply_button.setEnabled(False)
        self._table.setRowCount(0)
        self._table.hide()
        if self._worker is None:
            return True
        self._worker.job.cancel()
        return bool(self._worker.wait(3000))
