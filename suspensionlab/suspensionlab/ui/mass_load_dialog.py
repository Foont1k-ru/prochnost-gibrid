"""Явная оценка нагрузки по массе, без чтения или изменения проекта."""
from __future__ import annotations

from math import isfinite

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.mass_load import SymmetricMassLoad, symmetric_mass_load
from ..i18n import tr


class MassLoadDialog(QDialog):
    def __init__(self, role: str, side: str, maximum_load: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("mass_load.title"))
        self.resize(590, 440)
        self._maximum_load = maximum_load
        self.estimate: SymmetricMassLoad | None = None
        self.applied_load: float | None = None
        notice = QLabel(tr("mass_load.notice", role=role, side=side), self)
        notice.setWordWrap(True)
        self._fields = {key: QLineEdit(self) for key in ("mass", "axle_percent", "unsprung")}
        form = QFormLayout()
        for key, edit in self._fields.items():
            edit.setPlaceholderText(tr("mass_load.required"))
            edit.textChanged.connect(self._clear)
            form.addRow(tr(f"mass_load.{key}"), edit)
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
        layout.addWidget(notice)
        layout.addLayout(form)
        layout.addWidget(self._calculate_button)
        layout.addWidget(self._result)
        layout.addStretch()
        layout.addWidget(self._apply)
        layout.addWidget(close)
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
            estimate = symmetric_mass_load(parse("mass"), parse("axle_percent"), parse("unsprung"))
            # В исходном окне значение хранится с одним десятичным знаком, не допускаем скрытое ограничение диапазона.
            applied = float(f"{estimate.sprung_load_n:.1f}")
            if not 0 < applied <= self._maximum_load:
                raise ValueError
        except (ValueError, OverflowError):
            self._result.setText(tr("mass_load.invalid", maximum=f"{self._maximum_load:.1f}"))
            return
        self.estimate = estimate
        self.applied_load = applied
        self._result.setText(tr("mass_load.result", total=f"{estimate.corner_total_kg:.3f}",
                                reaction=f"{estimate.tire_reaction_n:.2f}", sprung=f"{estimate.corner_sprung_kg:.3f}",
                                load=f"{estimate.sprung_load_n:.2f}", applied=f"{applied:.1f}"))
        self._apply.setEnabled(True)

    def _accept_estimate(self) -> None:
        if self.estimate is not None and self.applied_load is not None:
            self.accept()
