"""Компактный незакреплённый редактор изгиба поверх CAD, без модального окна."""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget


class InlineTubeSketch(QFrame):
    applied = Signal(object)
    cancelled = Signal()
    candidateChanged = Signal(object)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName('inlineTubeSketch')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.title = QLabel(self)
        layout.addWidget(self.title)
        hint = QLabel('Вершина продолжений оси и радиус, мм. Это не длины детали.', self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QGridLayout()
        self.fields: dict[str, QLineEdit] = {}
        for index, key in enumerate(('X', 'Y', 'Z', 'R')):
            label = QLabel(key, self)
            field = QLineEdit(self)
            field.setAccessibleName('Эскиз трубы: ' + key)
            field.setObjectName('inline_sketch_' + key.lower())
            field.setMaxLength(64)
            field.setMaximumWidth(84)
            field.installEventFilter(self)
            field.textChanged.connect(self._changed)
            form.addWidget(label, 0, index)
            form.addWidget(field, 1, index)
            self.fields[key] = field
        layout.addLayout(form)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        apply_button = QPushButton('Применить', self)
        apply_button.setAutoDefault(False)
        apply_button.clicked.connect(self._apply)
        close_button = QPushButton('Закрыть', self)
        close_button.setAutoDefault(False)
        close_button.clicked.connect(self.cancelled.emit)
        row.addWidget(apply_button)
        row.addWidget(close_button)
        layout.addLayout(row)
        self.setMaximumWidth(380)
        self.hide()

    def begin(self, leg: str, vertex: tuple[float, float, float], radius: float | None) -> None:
        self.title.setText('Эскиз · ' + ('передняя труба' if leg == 'front' else 'задняя труба'))
        self.status.setText('Для прямой трубы сначала задайте новую вершину и радиус.' if radius is None else '')
        self.blockSignals(True)
        try:
            for key, value in zip(('X', 'Y', 'Z', 'R'), (*vertex, radius), strict=True):
                self.fields[key].setText('' if value is None else repr(value))
        finally:
            self.blockSignals(False)
        self.adjustSize()
        self.show()
        self.raise_()

    def values(self) -> tuple[float, float, float, float]:
        try:
            values = tuple(float(self.fields[key].text().strip().replace(',', '.')) for key in ('X', 'Y', 'Z', 'R'))
        except ValueError as error:
            raise ValueError('Введите координаты XYZ и радиус.') from error
        if not all(math.isfinite(value) for value in values):
            raise ValueError('Все значения должны быть конечными числами.')
        return values  # type: ignore[return-value]

    def _changed(self, *_args: object) -> None:
        try:
            values = self.values()
        except ValueError:
            self.candidateChanged.emit(None)
            return
        self.candidateChanged.emit(values)

    def _apply(self) -> None:
        try:
            values = self.values()
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.applied.emit(values)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched in self.fields.values() and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._apply()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.cancelled.emit()
                return True
        return super().eventFilter(watched, event)
