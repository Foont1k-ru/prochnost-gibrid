"""Изолированная проверка пересечений и расстояний деталей снимка."""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSignalBlocker, QThread, Signal
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
    PairProximity,
    PairwiseResult,
    ProximityResult,
    SuggestionResult,
)
from ..model.fixed_arm_clearances import TUBE_PAIR, validate_requirements


def _requirement_status(pair: PairProximity, minimum: float | None) -> str:
    if minimum is None:
        return 'Не задано'
    if pair.status in ('error', 'uncertain_overlap'):
        return 'Не проверено'
    if pair.status == 'intersection':
        return 'Не выполнено: пересечение'
    if minimum == 0 and pair.status in ('near', 'gap'):
        return '0: касание допускается'
    if pair.status == 'near' or pair.distance_mm is None:
        return 'Не выполнено: близость'
    if pair.distance_mm < minimum - DISTANCE_TOLERANCE_MM:
        return 'Не выполнено'
    if pair.distance_mm < minimum + DISTANCE_TOLERANCE_MM:
        return 'У границы: не подтверждено'
    return 'Выполнено на снимке'


class _OverlapReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], token: int, parent: QWidget, *,
                 all_parts: bool = False, proximity: bool = False,
                 suggestion: tuple[str, str, float] | None = None,
                 requirements: dict[str, float] | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.token = token
        self.all_parts = all_parts
        self.proximity = proximity
        self.suggestion = suggestion
        self.requirements = dict(requirements or {})
        self.job = FixedArmOverlapJob()

    def run(self) -> None:
        try:
            result: ProximityResult | PairwiseResult | OverlapResult | SuggestionResult
            if self.suggestion is not None:
                result = self.job.run_suggestion(self.document, *self.suggestion, requirements=self.requirements)
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
        self._requirements: dict[str, float] = {}
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
        hint = QLabel('Выберите строку расстояний и нажмите «Задать» для её минимума; '
                      '«Снять» удаляет требование. В актуальном CAD показана одна пара ближайших точек. '
                      'Подбор не применяется автоматически.', self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self._minimum = QLineEdit(self)
        self._minimum.setPlaceholderText('Минимальный зазор выбранной пары, мм')
        self._minimum.setMaxLength(32)
        self._minimum.textChanged.connect(self._requirement_changed)
        row.addWidget(self._minimum)
        self._set_minimum = QPushButton('Задать', self)
        self._set_minimum.setEnabled(False)
        self._set_minimum.clicked.connect(self._commit_requirement)
        row.addWidget(self._set_minimum)
        self._remove_minimum = QPushButton('Снять', self)
        self._remove_minimum.setEnabled(False)
        self._remove_minimum.clicked.connect(self._remove_requirement)
        row.addWidget(self._remove_minimum)
        layout.addLayout(row)
        self._suggest_button = QPushButton('Подобрать подрезку', self)
        self._suggest_button.setEnabled(False)
        self._suggest_button.clicked.connect(self._start_suggestion)
        layout.addWidget(self._suggest_button)
        self._suggest_status = QLabel('Требуемый зазор не задан; проверка требования не выполнена.', self)
        self._suggest_status.setWordWrap(True)
        layout.addWidget(self._suggest_status)
        self._apply_button = QPushButton('Применить предложение…', self)
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._confirm_suggestion)
        layout.addWidget(self._apply_button)

    def set_apply_callback(self, callback: Callable[[dict[str, Any], SuggestionResult], None]) -> None:
        self._apply_callback = callback

    def requirements(self) -> dict[str, float]:
        return dict(self._requirements)

    def set_requirements(self, values: dict[str, float], *, housings: bool) -> None:
        validated = validate_requirements(values, housings=housings)
        if validated != self._requirements and self._worker is not None:
            self.generation += 1
            self._worker.job.cancel()
        self._requirements = validated
        self._suggestion = None
        self._apply_button.setEnabled(False)
        self._requirement_pair = None
        self._requirement_changed()
        self._update_requirement_cells()

    def has_uncommitted_requirement(self) -> bool:
        if self._requirement_pair is None:
            return False
        saved = self._requirements.get('|'.join(self._requirement_pair))
        text = self._minimum.text().strip()
        if not text:
            return saved is not None
        value = self._minimum_value()
        return value is None or value != saved

    def clear_housing_requirements(self) -> bool:
        retained = {key: value for key, value in self._requirements.items() if key == TUBE_PAIR}
        changed = retained != self._requirements
        if changed:
            self.set_requirements(retained, housings=False)
        return changed

    def set_document(self, document: dict[str, Any] | None) -> None:
        self.generation += 1
        self._document = document
        self.markersRequested.emit(())
        self._proximity = None
        self._requirement_pair = None
        self._suggestion = None
        self._minimum.clear()
        self._suggest_button.setEnabled(False)
        self._set_minimum.setEnabled(False)
        self._remove_minimum.setEnabled(False)
        self._apply_button.setEnabled(False)
        self._suggest_status.setText('Требования сохранены в параметрах, но на текущей геометрии не проверены.'
                                     if self._requirements else 'Требуемый зазор не задан; проверка не выполнена.')
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
        key_text = '|'.join(key) if key else None
        saved = self._requirements.get(key_text) if key_text else None
        if key != self._requirement_pair:
            self._requirement_pair = key
            with QSignalBlocker(self._minimum):
                self._minimum.setText(repr(saved) if saved is not None else '')
        value = self._minimum_value()
        points = pair.points if pair is not None and pair.status == 'gap' and pair.points is not None else ()
        self.markersRequested.emit(points)
        enabled = not self._closed and self._worker is None and pair is not None
        self._set_minimum.setEnabled(enabled and value is not None and value != saved)
        self._remove_minimum.setEnabled(enabled and saved is not None)
        self._suggest_button.setEnabled(enabled and saved is not None and value == saved)
        if pair is None:
            self._suggest_status.setText('Выберите пару после расчёта; требования до этого не проверены.')
        elif saved is None:
            self._suggest_status.setText('Требование не задано. Введите 0 или минимум больше 0,00001 и до 100 мм '
                                         'и нажмите «Задать»; 0 допускает касание.')
        else:
            note = ' Изменённый ввод не принят: нажмите «Задать».' if value != saved else ''
            self._suggest_status.setText(f'Выбранная пара: минимум {saved:g} мм — '
                                         f'{_requirement_status(pair, saved)}.{note}')

    def _commit_requirement(self) -> None:
        value, key = self._minimum_value(), self._requirement_pair
        if value is None or key is None or self._worker is not None or self._document is None:
            return
        if not self._is_current(self._document):
            self.set_document(None)
            return
        self._requirements['|'.join(key)] = value
        self._requirement_changed()
        self._update_requirement_cells()

    def _remove_requirement(self) -> None:
        key = self._requirement_pair
        if key is None or self._worker is not None or self._document is None:
            return
        if not self._is_current(self._document):
            self.set_document(None)
            return
        self._requirements.pop('|'.join(key), None)
        with QSignalBlocker(self._minimum):
            self._minimum.clear()
        self._requirement_changed()
        self._update_requirement_cells()

    def _update_requirement_cells(self) -> None:
        if self._proximity is None or self._table.columnCount() != 7:
            return
        with QSignalBlocker(self._table):
            for row, pair in enumerate(self._proximity.pairs):
                minimum = self._requirements.get(f'{pair.left}|{pair.right}')
                self._table.setItem(row, 5, QTableWidgetItem('Не задано' if minimum is None else f'{minimum:g}'))
                self._table.setItem(row, 6, QTableWidgetItem(_requirement_status(pair, minimum)))

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
        if self._requirements.get(f'{pair.left}|{pair.right}') != value:
            return
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
                                proximity=proximity, suggestion=suggestion, requirements=self._requirements)
        self._worker = worker
        self._button.setEnabled(False)
        self._all_button.setEnabled(False)
        self._distance_button.setEnabled(False)
        self._suggest_button.setEnabled(False)
        self._set_minimum.setEnabled(False)
        self._remove_minimum.setEnabled(False)
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
        unconfirmed = sum(_requirement_status(p, self._requirements[f'{p.left}|{p.right}']) not in
                          ('Выполнено на снимке', '0: касание допускается') for p in result.after.pairs
                          if f'{p.left}|{p.right}' in self._requirements)
        self._suggest_status.setText(f'Предложение: подрезать {target} трубу {labels[result.kind or ""]}; '
                                     f'радиальный размер реза {result.radial_clearance_mm:g} мм. '
                                     f'Расчётный зазор выбранной пары {after.distance_mm:.6g} мм; '
                                     f'пересечений после реза: {conflicts}; заданных требований не подтверждено: {unconfirmed}. '
                                     'Прочность, сварка и движение не удостоверены.')
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
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(['Пара', 'Расстояние, мм', 'Объём, мм³', 'Порог, мм³', 'Результат',
                                              'Минимум, мм', 'Требование'])
        for index in (1, 2, 3, 4, 5, 6):
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
        self._update_requirement_cells()
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
        pair = self._proximity.pairs[row] if self._proximity is not None and 0 <= row < len(self._proximity.pairs) else None
        saved = self._requirements.get(f'{pair.left}|{pair.right}') if pair is not None else None
        value = self._minimum_value()
        self._set_minimum.setEnabled(enabled and pair is not None and value is not None and value != saved)
        self._remove_minimum.setEnabled(enabled and pair is not None and saved is not None)
        self._suggest_button.setEnabled(enabled and pair is not None and saved is not None and value == saved)
        self._apply_button.setEnabled(enabled and self._suggestion is not None and self._apply_callback is not None)

    def shutdown(self) -> bool:
        self._closed = True
        self.generation += 1
        self._document = None
        self._button.setEnabled(False)
        self._all_button.setEnabled(False)
        self._distance_button.setEnabled(False)
        self._suggest_button.setEnabled(False)
        self._set_minimum.setEnabled(False)
        self._remove_minimum.setEnabled(False)
        self._apply_button.setEnabled(False)
        self._table.setRowCount(0)
        self._table.hide()
        if self._worker is None:
            return True
        self._worker.job.cancel()
        return bool(self._worker.wait(3000))
