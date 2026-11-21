"""Явный ввод двух корпусов без выбора размеров или осей за пользователя."""
from __future__ import annotations

import math
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..model.fixed_arm_housings import HousingError, validate_housings


class FixedArmHousingsDialog(QDialog):
    def __init__(self, values: dict[str, Any] | None = None, parent: QWidget | None = None, *,
                 anchors: tuple[tuple[float, float, float], ...] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Два корпуса втулок · явные параметры')
        self.resize(500, 480)
        self.result_values: dict[str, Any] | None = None
        self.fields: dict[str, dict[str, QLineEdit]] = {}
        self.confirm_center: dict[str, QCheckBox] = {}
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        body = QWidget(scroll)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        layout = QVBoxLayout(body)
        if anchors is not None and len(anchors) >= 2:
            note_text = ('Центры корпусов совпадают с внутренними опорами снимка. '
                         'Направление оси предлагается по линии между опорами — это предположение, '
                         'не измерение реальной втулки. При необходимости измените компоненты направления. '
                         'Если точка опоры не является центром корпуса, этот режим не подходит.')
        else:
            note_text = ('Задайте размеры и направление оси; подтвердите совпадение центра корпуса с опорой. '
                         'Если точка опоры не является центром корпуса, этот режим не подходит.')
        note = QLabel(note_text, self)
        note.setWordWrap(True)
        layout.addWidget(note)
        default_axis: tuple[float, float, float] | None = None
        if anchors is not None and len(anchors) >= 2:
            direction = tuple(anchors[1][i] - anchors[0][i] for i in range(3))
            length = math.hypot(*direction)
            if math.isfinite(length) and length >= 1e-9:
                default_axis = (direction[0] / length, direction[1] / length, direction[2] / length)
        for index, (leg, title) in enumerate((('front', 'Передний корпус'), ('rear', 'Задний корпус'))):
            box = QGroupBox(title, self)
            group = QVBoxLayout(box)
            if anchors is not None and len(anchors) >= 2:
                point = anchors[index]
                center = QLabel(f'Центр: опора снимка (XYZ, округлено: {point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f}) мм', box)
                center.setWordWrap(True)
                group.addWidget(center)
            form = QFormLayout()
            self.fields[leg] = {}
            for key, label in (('outer_diameter_mm', 'Наружный диаметр, мм'),
                               ('bore_diameter_mm', 'Диаметр отверстия, мм'), ('length_mm', 'Длина, мм'),
                               ('axis_x', 'Направление оси X'), ('axis_y', 'Направление оси Y'),
                               ('axis_z', 'Направление оси Z')):
                field = QLineEdit(box)
                field.setMaxLength(64)
                field.setPlaceholderText('Введите значение')
                field.setObjectName(f'{leg}_{key}')
                form.addRow(label, field)
                self.fields[leg][key] = field
            group.addLayout(form)
            check = QCheckBox('Подтверждаю: центр корпуса совпадает с точкой опоры', box)
            self.confirm_center[leg] = check
            if anchors is not None and len(anchors) >= 2:
                check.setChecked(True)
                check.hide()
            else:
                group.addWidget(check)
            if default_axis is not None:
                for key, component in zip(('axis_x', 'axis_y', 'axis_z'), default_axis, strict=True):
                    self.fields[leg][key].setText(repr(component))
            layout.addWidget(box)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Применить')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
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
