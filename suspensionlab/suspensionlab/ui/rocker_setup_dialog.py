"""Явный ввод экспериментальной геометрии тяги и коромысла."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.rocker_kinematics import RockerError, RockerGeometry, solve_rocker
from ..i18n import tr
from ..model.kinematic_elements import RockerSetup

_FIELDS = ('pivot', 'axis', 'rod_rocker', 'rod_suspension', 'damper_rocker', 'damper_body')


class RockerSetupDialog(QDialog):
    """Пустой новый ввод не превращается в выдуманную геометрию."""

    def __init__(self, type_code: str, initial: RockerSetup | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr('rocker_setup.title'))
        self.resize(670, 580)
        self.initial = initial
        self.result_setup: RockerSetup | None = initial
        layout = QVBoxLayout(self)
        explanation = QLabel(tr('rocker_setup.intro'), self)
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr('rocker_setup.mode'), self))
        self.mode = QComboBox(self)
        self.mode.addItem(tr('rocker_setup.direct'), 'direct')
        self.mode.addItem(tr('rocker_setup.rocker'), 'rocker')
        self.mode.setCurrentIndex(1 if initial is not None and initial.enabled else 0)
        mode_row.addWidget(self.mode, 1)
        layout.addLayout(mode_row)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        grid = QGridLayout(content)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        grid.addWidget(QLabel(tr('rocker_setup.mount'), content), 0, 0)
        self.mount = QComboBox(content)
        self.mount.addItem(tr('rocker_setup.select_mount'), None)
        self.mount.addItem(tr('rocker_setup.upright'), 'upright')
        if type_code == 'double_wishbone':
            self.mount.addItem(tr('rocker_setup.lower_arm'), 'lower_arm')
        if initial is not None:
            self.mount.setCurrentIndex(max(0, self.mount.findData(initial.mount)))
        grid.addWidget(self.mount, 0, 1, 1, 3)
        for index, axis in enumerate(('X', 'Y', 'Z'), start=1):
            grid.addWidget(QLabel(axis, content), 1, index)
        self.inputs: dict[tuple[str, int], QLineEdit] = {}
        for row, name in enumerate(_FIELDS, start=2):
            label = QLabel(tr(f'rocker_setup.{name}'), content)
            label.setWordWrap(True)
            grid.addWidget(label, row, 0)
            for axis_idx in range(3):
                edit = QLineEdit(content)
                edit.setPlaceholderText('—')
                edit.setAccessibleName(tr(f'rocker_setup.{name}') + ' ' + 'XYZ'[axis_idx])
                if initial is not None:
                    edit.setText(repr(getattr(initial, name)[axis_idx]))
                self.inputs[(name, axis_idx)] = edit
                grid.addWidget(edit, row, axis_idx + 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.accepted.connect(self._apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.mode.currentIndexChanged.connect(lambda: content.setEnabled(self.mode.currentData() == 'rocker'))
        content.setEnabled(self.mode.currentData() == 'rocker')

    def _apply(self) -> None:
        if self.mode.currentData() == 'direct':
            self.result_setup = replace(self.initial, enabled=False) if self.initial is not None else None
            self.accept()
            return
        try:
            mount = self.mount.currentData()
            if mount is None:
                raise ValueError('mount')
            def point(name: str) -> tuple[float, float, float]:
                values = [float(self.inputs[(name, axis_idx)].text().strip().replace(',', '.'))
                          for axis_idx in range(3)]
                return values[0], values[1], values[2]
            setup = RockerSetup(True, mount, point('pivot'), point('axis'), point('rod_rocker'),
                                point('rod_suspension'), point('damper_rocker'), point('damper_body'))
            geometry = RockerGeometry(setup.pivot, setup.axis, setup.rod_rocker, setup.rod_suspension,
                                      setup.damper_rocker, setup.damper_body)
            solve_rocker(geometry, geometry.rod_suspension)
        except (ValueError, RockerError, OverflowError, TypeError):
            self.error.setText(tr('rocker_setup.invalid'))
            return
        self.result_setup = setup
        self.accept()
