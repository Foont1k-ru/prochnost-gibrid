"""Явный экспериментальный поиск условного баланса одной стороны."""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.equilibrium import EquilibriumPathError, EquilibriumResult, SpringEquilibrium
from ..core.stroke import StrokeLimits
from ..i18n import tr
from .controller import AppController


class EquilibriumDialog(QDialog):
    """Отдельное исследование без записи входов и результатов в проект."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(tr("equilibrium_ui.title"))
        self.resize(860, 650)
        self._role = QComboBox(self)
        self._side = QComboBox(self)
        for role in ("front", "rear"):
            self._role.addItem(tr(f"tree.{role}"), role)
        for side in ("left", "right"):
            self._side.addItem(tr(f"hp.side.{side}"), side)
        self._from = self._number(-100, 100, -30)
        self._to = self._number(-100, 100, 30)
        self._load = self._number(0, 100000, 0)
        self._length = self._number(0, 2000, 0)
        self._bind = self._number(0, 2000, 0)
        self._damper = QCheckBox(tr("equilibrium_ui.damper"), self)
        self._damper_min = self._number(0, 2000, 0)
        self._damper_max = self._number(0, 2000, 0)

        left = QFormLayout()
        right = QFormLayout()
        for key, widget in (("role", self._role), ("side", self._side), ("from", self._from),
                            ("to", self._to), ("load", self._load)):
            left.addRow(tr(f"equilibrium_ui.{key}"), widget)
        for key, widget in (("length", self._length), ("bind", self._bind)):
            right.addRow(tr(f"equilibrium_ui.{key}"), widget)
        right.addRow(self._damper)
        right.addRow(tr("equilibrium_ui.damper_min"), self._damper_min)
        right.addRow(tr("equilibrium_ui.damper_max"), self._damper_max)
        fields = QHBoxLayout()
        fields.addLayout(left)
        fields.addLayout(right)
        notice = QLabel(tr("equilibrium_ui.notice"), self)
        notice.setWordWrap(True)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._output = QLabel(self)
        self._output.setWordWrap(True)
        self._output.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._result: EquilibriumResult | None = None
        self._run = QPushButton(tr("equilibrium_ui.run"), self)
        self._run.clicked.connect(self._calculate)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.button(QDialogButtonBox.StandardButton.Close).setText(tr("analysis.close"))
        close.rejected.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self._run)
        buttons.addStretch()
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addLayout(fields)
        layout.addWidget(self._status)
        layout.addWidget(self._output)
        layout.addStretch()
        layout.addLayout(buttons)
        for combo in (self._role, self._side):
            combo.currentIndexChanged.connect(self._invalidate)
        for number in (self._from, self._to, self._load, self._length, self._bind,
                       self._damper_min, self._damper_max):
            number.valueChanged.connect(self._invalidate)
        self._damper.toggled.connect(self._invalidate)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._invalidate)
        self._invalidate()

    def _number(self, minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox(self)
        box.setDecimals(1)
        box.setRange(minimum, maximum)
        box.setValue(value)
        return box

    def _invalidate(self, *_args: object) -> None:
        self._result = None
        self._output.clear()
        self._damper_min.setEnabled(self._damper.isChecked())
        self._damper_max.setEnabled(self._damper.isChecked())
        supported = self.controller.project.axle(str(self._role.currentData())).type_code == "double_wishbone"
        self._run.setEnabled(supported)
        self._status.setText(tr("equilibrium_ui.ready" if supported else "analysis.unsupported"))

    def _calculate(self) -> None:
        self._result = None
        self._output.clear()
        axle = self.controller.project.axle(str(self._role.currentData()))
        if axle.type_code != "double_wishbone":
            self._status.setText(tr("analysis.unsupported"))
            return
        try:
            if self._load.value() <= 0 or self._length.value() <= 0:
                raise ValueError(tr("equilibrium_ui.required"))
            limits = None
            if self._damper.isChecked():
                if self._damper_min.value() <= 0 or self._damper_max.value() <= 0:
                    raise ValueError(tr("equilibrium_ui.damper_required"))
                limits = StrokeLimits(self._damper_min.value(), self._damper_max.value())
            side: Literal["left", "right"] = "left" if self._side.currentData() == "left" else "right"
            problem = SpringEquilibrium(
                axle, self._length.value(), side=side, coil_bind_length_mm=self._bind.value() or None,
                damper_mount="lower_arm" if self._damper.isChecked() else None, damper_limits=limits,
                max_step_mm=1.0,
            )
            result = problem.find(self._load.value(), self._from.value(), self._to.value(),
                                  travel_tolerance_mm=0.1, path_step_mm=1.0)
        except EquilibriumPathError as error:
            failure = error.path.failure
            assert failure is not None
            self._status.setText(tr("equilibrium_ui.path_error", requested=f"{failure.requested_travel_mm:.3f}",
                                    failure=f"{failure.failure_travel_mm:.3f}", reason=failure.reason))
            return
        except (ValueError, ArithmeticError) as error:
            self._status.setText(tr("equilibrium_ui.error", reason=str(error)))
            return
        self._result = result
        point = result.estimate
        assert result.path is not None
        self._status.setText(tr("equilibrium_ui.success"))
        self._output.setText(tr(
            "equilibrium_ui.result", lower=f"{result.lower.travel_mm:.4f}", upper=f"{result.upper.travel_mm:.4f}",
            lower_residual=f"{result.lower.residual_n:+.4f}", upper_residual=f"{result.upper.residual_n:+.4f}",
            travel=f"{point.travel_mm:.4f}", length=f"{point.spring.length_mm:.4f}",
            spring_force=f"{point.spring.force_n:.4f}", ratio=f"{point.motion_ratio:.6f}",
            support=f"{point.wheel_support_n:.4f}", residual=f"{point.residual_n:+.4f}",
            samples=len(result.path.samples), step=f"{result.path.actual_step_mm:.4f}",
            bind=tr("equilibrium_ui.checked" if self._bind.value() else "equilibrium_ui.unchecked"),
            damper=tr("equilibrium_ui.checked" if self._damper.isChecked() else "equilibrium_ui.unchecked"),
        ))
