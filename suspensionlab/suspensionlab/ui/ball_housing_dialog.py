"""Явный ввод размеров отдельного корпуса у шаровой."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..model.ball_housing import validate_ball_housing


class BallHousingDialog(QDialog):
    def __init__(self, values: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Центральный корпус · явные параметры')
        self.result_values: dict[str, Any] | None = None
        self.fields: dict[str, QLineEdit] = {}
        layout = QVBoxLayout(self)
        note = QLabel('Центр корпуса = центр шаровой + смещение XYZ, мм. '
                      'Направление задаётся вектором оси XYZ. Начальные ось Z и нулевое смещение — '
                      'предположения, проверьте их. Обе трубы направляются к центру корпуса и '
                      'подрезаются по его наружной поверхности; шаровая и сварка не моделируются.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        for key, label in (('outer_diameter_mm', 'Наружный диаметр, мм'),
                           ('bore_diameter_mm', 'Диаметр отверстия, мм'), ('length_mm', 'Длина, мм'),
                           ('axis_x', 'Направление оси X'), ('axis_y', 'Направление оси Y'),
                           ('axis_z', 'Направление оси Z'), ('offset_x', 'Смещение X, мм'),
                           ('offset_y', 'Смещение Y, мм'), ('offset_z', 'Смещение Z, мм')):
            field = QLineEdit(self)
            field.setMaxLength(64)
            field.setObjectName('ball_' + key)
            field.setPlaceholderText('Введите значение')
            self.fields[key] = field
            form.addRow(label, field)
        layout.addLayout(form)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Применить')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if values is None:
            for key, value in (('axis_x', 0), ('axis_y', 0), ('axis_z', 1),
                               ('offset_x', 0), ('offset_y', 0), ('offset_z', 0)):
                self.fields[key].setText(str(value))
        else:
            data = validate_ball_housing(values)
            for key in ('outer_diameter_mm', 'bore_diameter_mm', 'length_mm'):
                self.fields[key].setText(repr(data[key]))
            for prefix, vector in (('axis', data['axis']), ('offset', data['offset_mm'])):
                for component, value in zip(('x', 'y', 'z'), vector, strict=True):
                    self.fields[f'{prefix}_{component}'].setText(repr(value))

    def accept(self) -> None:
        try:
            def number(key: str) -> float:
                return float(self.fields[key].text().strip().replace(',', '.'))

            self.result_values = validate_ball_housing({
                'outer_diameter_mm': number('outer_diameter_mm'),
                'bore_diameter_mm': number('bore_diameter_mm'),
                'length_mm': number('length_mm'),
                'axis': [number(f'axis_{c}') for c in ('x', 'y', 'z')],
                'offset_mm': [number(f'offset_{c}') for c in ('x', 'y', 'z')],
            })
        except ValueError as error:
            self._status.setText(f'Данные не приняты: {error}. Заполните все поля.')
            return
        super().accept()
