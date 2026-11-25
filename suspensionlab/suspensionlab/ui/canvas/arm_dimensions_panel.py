"""Редактирование размеров рычага на основной схеме сверху."""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...model.arm_scheme_dimensions import Dimension, arm_codes, arm_dimensions, dimension_edits


class ArmDimensionsPanel(QFrame):
    """Показывает и изменяет отдельные проекционные размеры модели проекта."""

    def __init__(self, canvas, controller) -> None:
        super().__init__(canvas)
        self.canvas, self.controller = canvas, controller
        self.setObjectName('armDimensionsPanel')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.toggle = QToolButton(self)
        self.toggle.setText('Размеры рычага · вид сверху')
        self.toggle.setCheckable(True)
        outer.addWidget(self.toggle)
        self.body = QWidget(self)
        outer.addWidget(self.body)
        layout = QFormLayout(self.body)
        layout.setContentsMargins(0, 4, 0, 0)
        self.arm = QComboBox(self.body)
        self.arm.addItem('Передний нижний', 'lower')
        self.arm.addItem('Передний верхний', 'upper')
        layout.addRow('Рычаг', self.arm)
        self.reference = QComboBox(self.body)
        self.reference.setAccessibleName('Отсчёт положения по X')
        layout.addRow('Отсчёт положения X', self.reference)
        self.fields = {}
        self.buttons = {}
        dimensions: tuple[tuple[Dimension, str], ...] = (
            ('span_x', 'Опоры: расстояние по X'),
            ('ball_x', 'Шаровая от передней опоры: X'),
            ('ball_y', 'Шаровая от передней опоры: Y'),
            ('position_x', 'Передняя опора: X от отсчёта'),
        )
        for key, label in dimensions:
            row = QWidget(self.body)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            spin = QDoubleSpinBox(row)
            spin.setDecimals(3)
            spin.setRange(-2_000_000_000 if key == 'position_x' else 0, 2_000_000_000)
            spin.setSuffix(' мм')
            spin.setKeyboardTracking(False)
            spin.setAccessibleName(label)
            button = QPushButton('Применить', row)
            button.setAutoDefault(False)
            button.clicked.connect(partial(self._apply, key))
            spin.lineEdit().returnPressed.connect(partial(self._apply, key))
            row_layout.addWidget(spin)
            row_layout.addWidget(button)
            layout.addRow(label, row)
            self.fields[key] = spin
            self.buttons[key] = button
        note = QLabel('Проекция XY, левая сторона. X — вдоль автомобиля. '
                      'Шаровая общая с кулаком; движение влияет на связанные элементы.', self.body)
        note.setWordWrap(True)
        note.setMaximumWidth(320)
        layout.addRow(note)
        self.status = QLabel('', self.body)
        self.status.setWordWrap(True)
        self.status.setMaximumWidth(320)
        layout.addRow(self.status)
        self.body.hide()
        self.toggle.toggled.connect(self._toggle)
        self.arm.currentIndexChanged.connect(self._refresh)
        self.reference.currentIndexChanged.connect(self._refresh)
        canvas.viewChanged.connect(self._view_changed)
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._reset_reference)
        self._refresh()

    def _view_changed(self, mode: str) -> None:
        if mode != 'top':
            self.toggle.setChecked(False)
        self.canvas._dimension_hits.clear()

    def _toggle(self, checked: bool) -> None:
        self.canvas._dimension_hits.clear()
        if checked:
            self.canvas.set_view_mode('top')
        self.body.setVisible(checked)
        self.status.clear()
        self.adjustSize()
        self.canvas.update()

    def _reset_reference(self) -> None:
        with QSignalBlocker(self.reference):
            self.reference.setCurrentIndex(0)
        self._refresh()

    def _reference_x(self) -> float:
        code = self.reference.currentData()
        return 0. if code is None else float(self.controller.project.front.hardpoints[code].x)

    def _refresh(self, *_args) -> None:
        enabled = self.canvas.roles() == ('front',) and self.controller.project.front.type_code == 'double_wishbone'
        self.setVisible(enabled)
        if not enabled:
            return
        try:
            axle = self.controller.project.front
            codes = arm_codes(axle, self.arm.currentData())
            selected_reference = self.reference.currentData()
            with QSignalBlocker(self.reference):
                self.reference.clear()
                self.reference.addItem('Начало координат передней оси (X = 0)', None)
                for code in axle.point_codes():
                    if code in codes or code not in axle.hardpoints:
                        continue
                    spec = axle.spec.point(code)
                    self.reference.addItem(tr(spec.name_key) if spec else code, code)
                index = self.reference.findData(selected_reference)
                self.reference.setCurrentIndex(max(0, index))
            values = arm_dimensions(axle, self.arm.currentData(), reference_x=self._reference_x())
        except (ValueError, KeyError):
            self.body.setEnabled(False)
            self.status.setText('Точки рычага недоступны')
            return
        self.body.setEnabled(True)
        for key, value in values.items():
            with QSignalBlocker(self.fields[key]):
                self.fields[key].setValue(value)
        self.adjustSize()
        self.canvas.update()

    def _apply(self, key: Dimension, _checked: bool = False) -> None:
        self.fields[key].interpretText()
        try:
            edits = dimension_edits(self.controller.project.front, self.arm.currentData(), key,
                                    self.fields[key].value(), reference_x=self._reference_x())
            self.controller.move_points(edits)
        except (ValueError, KeyError) as error:
            self.status.setText(f'Размер не применён: {error}')
            self._refresh()
            return
        self.status.setText('Размер применён. Проверьте связанную геометрию подвески.')
        self._refresh()
