"""Явный пересчёт измеренных точек амортизатора в условные линейные коэффициенты."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.damper import linear_coefficient_from_point
from ..i18n import tr

MAX_DAMPING_COEFFICIENT = 10000.0


class DamperConversionDialog(QDialog):
    """Каждая сторона характеристики необязательна, но пара сила/скорость — целая."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("damper_conversion.title"))
        self.resize(650, 380)
        self._compression_force = QLineEdit(self)
        self._compression_speed = QLineEdit(self)
        self._rebound_force = QLineEdit(self)
        self._rebound_speed = QLineEdit(self)
        self._fields = (self._compression_force, self._compression_speed, self._rebound_force, self._rebound_speed)
        form = QFormLayout()
        for key, field in zip(("compression_force", "compression_speed", "rebound_force", "rebound_speed"),
                              self._fields, strict=True):
            field.setPlaceholderText(tr("damper_conversion.placeholder"))
            form.addRow(tr(f"damper_conversion.{key}"), field)
            field.textChanged.connect(self._update)
        notice = QLabel(tr("damper_conversion.notice"), self)
        notice.setWordWrap(True)
        self._result = QLabel(self)
        self._result.setWordWrap(True)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self._apply = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._apply.setText(tr("damper_conversion.apply"))
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("damper_conversion.cancel"))
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addLayout(form)
        layout.addWidget(self._result)
        layout.addStretch()
        layout.addWidget(self._buttons)
        self._values: tuple[float | None, float | None] = (None, None)
        self._update()

    def _pair(self, force: QLineEdit, speed: QLineEdit) -> float | None:
        force_text, speed_text = force.text().strip(), speed.text().strip()
        if not force_text and not speed_text:
            return None
        if not force_text or not speed_text:
            raise ValueError(tr("damper_conversion.incomplete"))
        try:
            force_n = float(force_text.replace(",", "."))
            speed_mm_s = float(speed_text.replace(",", "."))
            coefficient = linear_coefficient_from_point(force_n, speed_mm_s)
        except (ValueError, OverflowError) as error:
            raise ValueError(tr("damper_conversion.invalid")) from error
        if coefficient > MAX_DAMPING_COEFFICIENT:
            raise ValueError(tr("damper_conversion.too_large", maximum=MAX_DAMPING_COEFFICIENT))
        return coefficient

    def _update(self, *_args: object) -> None:
        self._values = (None, None)
        self._apply.setEnabled(False)
        try:
            compression = self._pair(self._compression_force, self._compression_speed)
            rebound = self._pair(self._rebound_force, self._rebound_speed)
        except ValueError as error:
            self._result.setText(str(error))
            return
        if compression is None and rebound is None:
            self._result.setText(tr("damper_conversion.empty"))
            return
        self._values = (compression, rebound)
        def display(value: float | None) -> str:
            return repr(value) if value is not None else tr("damper_conversion.unchanged")
        self._result.setText(tr("damper_conversion.preview", compression=display(compression), rebound=display(rebound)))
        self._apply.setEnabled(True)

    def coefficients(self) -> tuple[float | None, float | None]:
        """Значения float без округления, отсутствующую пару не заменяет нулём."""
        return self._values
