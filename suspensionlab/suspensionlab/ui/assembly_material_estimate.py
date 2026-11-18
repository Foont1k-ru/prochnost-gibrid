"""Справочная оценка объёма и массы независимых деталей снимка сборки."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from ..model.assembly_material_estimate import PartVolume, assembly_part_volumes, density_kg_m3
from ..model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint


def _display(value: float) -> str:
    return '<0,001' if 0 < value < 0.001 else f'{value:.3f}'


class AssemblyMaterialEstimate(QWidget):
    def __init__(self, parent: QWidget, *, is_current: Callable[[dict[str, Any]], bool]) -> None:
        super().__init__(parent)
        self._is_current = is_current
        self._document: dict[str, Any] | None = None
        self._fingerprint: str | None = None
        self._volumes: tuple[PartVolume, ...] = ()
        layout = QVBoxLayout(self)
        note = QLabel('Справочная оценка отдельных неподрезанных тел снимка .kima: '
                      'трубы, корпуса и при наличии условная пластина. Объёмы суммируются без вычитания '
                      'пересечений. Шаровая, сайлентблоки, крепёж и сварка не учтены. '
                      'Это не масса готового рычага и не проверка конструкции.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.density = QLineEdit(self)
        self.density.setMaxLength(64)
        self.density.setPlaceholderText('Не задана — масса не рассчитывается')
        self.density.setAccessibleName('Одинаковая плотность всех показанных деталей, кг на кубический метр')
        form.addRow('Плотность всех показанных деталей, кг/м³', self.density)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.result = QPlainTextEdit(self)
        self.result.setReadOnly(True)
        self.result.setAccessibleName('Объёмы и условная масса деталей')
        layout.addWidget(self.result, 1)
        self.density.textChanged.connect(self._refresh)

    def set_document(self, document: dict[str, Any]) -> None:
        try:
            code = assembly_snapshot_fingerprint(document)
        except (TypeError, ValueError, OverflowError, RecursionError):
            self._document, self._fingerprint, self._volumes = None, None, ()
            self._refresh()
            return
        if self._document == document and self._fingerprint == code:
            return
        self._document, self._fingerprint = deepcopy(document), code
        try:
            self._volumes = assembly_part_volumes(self._document)
        except (TypeError, ValueError, OverflowError, RecursionError):
            self._volumes = ()
        self._refresh()

    def _refresh(self, *_args: object) -> None:
        self.result.clear()
        try:
            current = self._document is not None and self._is_current(self._document)
        except (TypeError, ValueError, OverflowError, RecursionError):
            current = False
        if not current or not self._volumes:
            self.status.setText('Оценка недоступна или снимок изменился. Данные не изменены.')
            return
        try:
            density = density_kg_m3(self.density.text())
        except ValueError:
            self.status.setText('Проверьте плотность: от 0,000001 до 1 000 000 кг/м³; '
                                'пустое поле отключает массу. Это предел расчёта, не выбор материала.')
            return
        rows = []
        for part in self._volumes:
            line = f'{part.name} ({part.identifier}): {_display(part.volume_mm3 / 1000)} см³'
            if part.length_mm is not None:
                line += f'; длина оси между центрами {_display(part.length_mm)} мм'
            if density is not None:
                line += f'; условно {_display(part.volume_mm3 * density / 1e9)} кг'
            rows.append(line)
        total = sum(part.volume_mm3 for part in self._volumes)
        rows.append(f'Сумма объёмов отдельных тел: {_display(total / 1000)} см³')
        if density is not None:
            rows.append(f'Сумма условных масс: {_display(total * density / 1e9)} кг')
        self.result.setPlainText('\n'.join(rows))
        self.status.setText('Текущий снимок в редакторе, включая несохранённые изменения. '
                            'Плотность применяется одинаково ко всем деталям; '
                            'материал, пересечения и реальная масса не проверяются.' if density is not None else
                            'Текущий снимок в редакторе, включая несохранённые изменения. '
                            'Плотность не задана: показаны только объёмы.')
