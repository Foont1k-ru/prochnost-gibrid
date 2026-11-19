"""Явный ввод двух корпусов без выбора размеров или осей за пользователя."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..model.fixed_arm_housings import HousingError, validate_housings


class FixedArmHousingsDialog(QDialog):
    def __init__(self, values: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Два корпуса втулок · явные параметры')
        self.resize(500, 660)
        self.result_values: dict[str, Any] | None = None
        self.fields: dict[str, dict[str, QLineEdit]] = {}
        self.confirm_center: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        note = QLabel('Для каждого корпуса задайте размеры и направление оси в системе XYZ автомобиля. '
                      'Центр корпуса будет совмещён с соответствующей опорой только после подтверждения. '
                      'Если точка опоры не является центром корпуса, этот режим пока не подходит.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        for leg, title in (('front', 'Передний корпус'), ('rear', 'Задний корпус')):
            box = QGroupBox(title, self)
            group = QVBoxLayout(box)
            form = QFormLayout()
            self.fields[leg] = {}
            for key, label in (('outer_diameter_mm', 'Наружный диаметр, мм'),
                               ('bore_diameter_mm', 'Диаметр отверстия, мм'), ('length_mm', 'Длина, мм'),
                               ('axis_x', 'Ось X'), ('axis_y', 'Ось Y'), ('axis_z', 'Ось Z')):
                field = QLineEdit(box)
                field.setMaxLength(64)
                field.setPlaceholderText('Введите значение')
                field.setObjectName(f'{leg}_{key}')
                form.addRow(label, field)
                self.fields[leg][key] = field
            group.addLayout(form)
            check = QCheckBox('Подтверждаю: центр корпуса совпадает с точкой опоры', box)
            self.confirm_center[leg] = check
            group.addWidget(check)
            layout.addWidget(box)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Применить')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if values is not None:
            data = validate_housings(values)
            for leg in ('front', 'rear'):
                item = data[leg]
                for key in ('outer_diameter_mm', 'bore_diameter_mm', 'length_mm'):
                    self.fields[leg][key].setText(repr(item[key]))
                for index, key in enumerate(('axis_x', 'axis_y', 'axis_z')):
                    self.fields[leg][key].setText(repr(item['axis'][index]))
                self.confirm_center[leg].setChecked(True)

    def accept(self) -> None:
        try:
            result: dict[str, Any] = {}
            def number(fields: dict[str, QLineEdit], key: str) -> float:
                return float(fields[key].text().strip().replace(',', '.'))
            for leg in ('front', 'rear'):
                fields = self.fields[leg]
                result[leg] = {'outer_diameter_mm': number(fields, 'outer_diameter_mm'),
                               'bore_diameter_mm': number(fields, 'bore_diameter_mm'),
                               'length_mm': number(fields, 'length_mm'),
                               'axis': [number(fields, 'axis_x'), number(fields, 'axis_y'), number(fields, 'axis_z')],
                               'center_on_pivot': self.confirm_center[leg].isChecked()}
            self.result_values = validate_housings(result)
        except (ValueError, HousingError) as error:
            self._status.setText(f'Данные не приняты: {error}. Заполните все поля и подтверждения.')
            return
        super().accept()
