"""Общие пользовательские настройки приближённого STEP-просмотра."""
from __future__ import annotations

from math import isclose, isfinite

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr

CAD_DEVIATION_KEY = "cad_preview/deviation_mm"
DEFAULT_CAD_DEVIATION = 10.0


def read_cad_deviation(settings: QSettings) -> float:
    """Не доверяем содержимому INI: только конечное значение из диапазона поля."""
    raw = settings.value(CAD_DEVIATION_KEY, DEFAULT_CAD_DEVIATION)
    try:
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            return DEFAULT_CAD_DEVIATION
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_CAD_DEVIATION
    if not isfinite(value) or not 0.2 <= value <= 20.0 or not isclose(value * 10, round(value * 10), abs_tol=1e-9, rel_tol=0):
        return DEFAULT_CAD_DEVIATION
    return value


class CadPreviewSettingsDialog(QDialog):
    """Пресеты лишь выбирают тот же параметр; сохранение только по OK."""

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle(tr("cad_preview.settings_title"))
        self.resize(540, 240)
        notice = QLabel(tr("cad_preview.settings_notice"), self)
        notice.setWordWrap(True)
        self._quality = QComboBox(self)
        for key, value in (("fast", 10.0), ("balanced", 2.0), ("detailed", 0.2), ("custom", None)):
            self._quality.addItem(tr(f"cad_preview.quality.{key}"), value)
        self._deviation = QDoubleSpinBox(self)
        self._deviation.setRange(0.2, 20.)
        self._deviation.setDecimals(1)
        self._deviation.setSingleStep(0.5)
        self._deviation.setSuffix(tr("cad_preview.mm"))
        self._deviation.setValue(read_cad_deviation(settings))
        self._quality.currentIndexChanged.connect(self._preset_changed)
        self._deviation.valueChanged.connect(self._value_changed)
        self._value_changed()
        form = QFormLayout()
        form.addRow(tr("cad_preview.quality_label"), self._quality)
        form.addRow(tr("cad_preview.deviation"), self._deviation)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("cad_preview.settings_save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cad_preview.settings_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addLayout(form)
        layout.addStretch()
        layout.addWidget(buttons)

    def _preset_changed(self) -> None:
        value = self._quality.currentData()
        if value is not None:
            self._deviation.setValue(float(value))

    def _value_changed(self) -> None:
        index = self._quality.findData(self._deviation.value())
        self._quality.blockSignals(True)
        self._quality.setCurrentIndex(index if index >= 0 else self._quality.findData(None))
        self._quality.blockSignals(False)

    def accept(self) -> None:
        had_value = self._settings.contains(CAD_DEVIATION_KEY)
        old_value = self._settings.value(CAD_DEVIATION_KEY)
        self._settings.setValue(CAD_DEVIATION_KEY, self._deviation.value())
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            if had_value:
                self._settings.setValue(CAD_DEVIATION_KEY, old_value)
            else:
                self._settings.remove(CAD_DEVIATION_KEY)
            QMessageBox.warning(self, tr("cad_preview.settings_error_title"), tr("cad_preview.settings_error"))
            return
        super().accept()
