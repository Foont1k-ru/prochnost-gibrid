"""Явная оценка нагрузки по массе, без чтения или изменения проекта."""
from __future__ import annotations

from math import isfinite
from typing import Literal

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.mass_load import (
    CornerKey,
    FourWheelMassLoad,
    MassLoadEstimate,
    corner_mass_load,
    four_wheel_mass_load,
    symmetric_mass_load,
)
from ..i18n import tr


class MassLoadDialog(QDialog):
    def __init__(self, role: str, side: str, maximum_load: float, parent: QWidget | None = None, *,
                 corner_key: CornerKey | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("mass_load.title"))
        self.resize(620, 520)
        self._maximum_load = maximum_load
        self.estimate: MassLoadEstimate | None = None
        self.applied_load: float | None = None
        self._role, self._side = role, side
        self._corner_key = corner_key
        self._notice = QLabel(self)
        self._notice.setWordWrap(True)
        self._mode = QComboBox(self)
        for mode in ("symmetric", "weighed", "assumed"):
            self._mode.addItem(tr(f"mass_load.mode.{mode}"), mode)
        if corner_key is not None:
            for mode in ("four_weighed", "four_assumed"):
                self._mode.addItem(tr(f"mass_load.mode.{mode}"), mode)
        self._fields = {key: QLineEdit(self) for key in (
            "mass", "axle_percent", "wheel", "front_left", "front_right", "rear_left", "rear_right", "unsprung")}

        self._form = QFormLayout()
        for key, edit in self._fields.items():
            edit.setPlaceholderText(tr("mass_load.required"))
            edit.textChanged.connect(self._clear)
            self._form.addRow(tr(f"mass_load.{key}"), edit)
        self._calculate_button = QPushButton(tr("mass_load.calculate"), self)
        self._calculate_button.clicked.connect(self._calculate)
        self._result = QLabel(self)
        self._result.setWordWrap(True)
        self._apply = QPushButton(tr("mass_load.apply"), self)
        self._apply.clicked.connect(self._accept_estimate)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        close.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("mass_load.cancel"))
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(self._notice)
        mode_layout = QFormLayout()
        mode_layout.addRow(tr("mass_load.mode.label"), self._mode)
        content_layout.addLayout(mode_layout)
        content_layout.addLayout(self._form)
        content_layout.addWidget(self._calculate_button)
        content_layout.addWidget(self._result)
        content_layout.addStretch()
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._apply)
        layout.addWidget(close)
        self._mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def _mode_changed(self, *_args: object) -> None:
        mode = self._mode.currentData()
        symmetric = mode == "symmetric"
        four = mode in ("four_weighed", "four_assumed")
        self._form.setRowVisible(self._fields["mass"], symmetric)
        self._form.setRowVisible(self._fields["axle_percent"], symmetric)
        self._form.setRowVisible(self._fields["wheel"], not symmetric and not four)
        for key in ("front_left", "front_right", "rear_left", "rear_right"):
            self._form.setRowVisible(self._fields[key], four)
        key = "notice" if symmetric else "four_notice" if four else "wheel_notice"
        self._notice.setText(tr(f"mass_load.{key}", role=self._role, side=self._side))
        self._clear()

    def _clear(self, *_args: object) -> None:
        self.estimate = None
        self.applied_load = None
        self._apply.setEnabled(False)
        self._result.setText(tr("mass_load.empty"))

    def _calculate(self) -> None:
        self._clear()
        try:
            def parse(key: str) -> float:
                value = float(self._fields[key].text().strip().replace(",", "."))
                if not isfinite(value):
                    raise ValueError
                return value
            mode = self._mode.currentData()
            if mode == "symmetric":
                estimate: MassLoadEstimate = symmetric_mass_load(parse("mass"), parse("axle_percent"), parse("unsprung"))
            elif mode in ("weighed", "assumed"):
                estimate = corner_mass_load(parse("wheel"), parse("unsprung"), mode)
            elif mode in ("four_weighed", "four_assumed") and self._corner_key is not None:
                kind: Literal["weighed", "assumed"] = "weighed" if mode == "four_weighed" else "assumed"
                estimate = four_wheel_mass_load(parse("front_left"), parse("front_right"), parse("rear_left"),
                                                parse("rear_right"), self._corner_key, parse("unsprung"), kind)
            else:
                raise ValueError
            # В исходном окне значение хранится с одним десятичным знаком, не допускаем скрытое ограничение диапазона.
            applied = float(f"{estimate.sprung_load_n:.1f}")
            if not 0 < applied <= self._maximum_load:
                raise ValueError
        except (ValueError, OverflowError):
            mode = self._mode.currentData()
            key = "invalid" if mode == "symmetric" else "four_invalid" if mode in ("four_weighed", "four_assumed") else "wheel_invalid"
            self._result.setText(tr(f"mass_load.{key}", maximum=f"{self._maximum_load:.1f}"))
            return
        self.estimate = estimate
        self.applied_load = applied
        if isinstance(estimate, FourWheelMassLoad):
            self._result.setText(tr("mass_load.four_result", total=f"{estimate.total_kg:.3f}",
                                    front=f"{estimate.front_kg:.3f}", rear=f"{estimate.rear_kg:.3f}",
                                    front_pct=f"{estimate.front_percent:.2f}", rear_pct=f"{estimate.rear_percent:.2f}",
                                    left=f"{estimate.left_kg:.3f}", right=f"{estimate.right_kg:.3f}",
                                    corner=f"{estimate.corner_total_kg:.3f}", reaction=f"{estimate.tire_reaction_n:.2f}",
                                    sprung=f"{estimate.corner_sprung_kg:.3f}", load=f"{estimate.sprung_load_n:.2f}",
                                    applied=f"{applied:.1f}"))
        else:
            result_key = "result" if self._mode.currentData() == "symmetric" else "wheel_result"
            self._result.setText(tr(f"mass_load.{result_key}", total=f"{estimate.corner_total_kg:.3f}",
                                    reaction=f"{estimate.tire_reaction_n:.2f}", sprung=f"{estimate.corner_sprung_kg:.3f}",
                                    load=f"{estimate.sprung_load_n:.2f}", applied=f"{applied:.1f}"))
        self._apply.setEnabled(True)

    def _accept_estimate(self) -> None:
        if self.estimate is not None and self.applied_load is not None:
            self.accept()
