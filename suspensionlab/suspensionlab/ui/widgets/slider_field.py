"""Строка параметра: ползунок + независимое числовое поле (требование Р-1).

Поведение по ТЗ §6.3:

* ползунок и поле синхронизированы в обе стороны;
* поле **не ограничено** диапазоном ползунка: при вводе значения за его
  пределами диапазон автоматически расширяется (настройка
  ``auto_extend``) либо поле подсвечивается жёлтым с пояснением;
* ввод понимает выражения и единицы: ``120+15/2``, ``12 см``, ``1"``;
* клавиатура: ↑/↓ — шаг, Shift — ×10, Ctrl — ×0,1, Home/End — границы,
  Esc — возврат к исходному значению;
* колесо мыши над полем (в фокусе) — шаг;
* 🔒 фиксация, ↺ сброс, ⋯ настройка границ и шага.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...model.param_specs import ParamSpec
from ...model.units import UnitConversionError, UnitKind, UnitSettings  # noqa: F401  (тип используется в документации)
from .glyphs import INFO, LOCK, MORE, RESET, UNLOCK
from .tooltip import install_tooltip


class SliderField(QWidget):
    """Ползунок с независимым числовым полем и полным набором опций."""

    valueChanged = Signal(float)
    lockChanged = Signal(bool)
    helpRequested = Signal(str)

    def __init__(
        self,
        spec: ParamSpec,
        units: UnitSettings,
        default: float,
        parent: QWidget | None = None,
        auto_extend: bool = True,
        locked: bool = False,
    ) -> None:
        super().__init__(parent)
        self._spec = spec
        self._units = units
        self._kind: UnitKind = spec.unit
        self._step = float(spec.step) if spec.step else 1.0
        self._minimum = float(spec.minimum)
        self._maximum = float(spec.maximum)
        self._default = float(default)
        self._value = float(default)
        self._auto_extend = auto_extend
        self._locked = locked
        self._invalid = False

        self._build_ui()
        self.set_value(default, emit=False)
        self.set_locked(locked)

    # ------------------------------------------------------------------ вёрстка
    def _build_ui(self) -> None:
        """Создаёт элементы строки параметра."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(4)
        self._title = QLabel(tr(self._spec.title_key))
        self._title.setWordWrap(False)
        self._title.setMinimumWidth(80)
        top.addWidget(self._title, 1)

        self._info_button = QToolButton(self)
        self._info_button.setText(INFO)
        self._info_button.setAutoRaise(True)
        self._info_button.setToolTip(tr("insp.info"))
        self._info_button.clicked.connect(lambda: self.helpRequested.emit(self._spec.help_key))
        top.addWidget(self._info_button)

        self._lock_button = QToolButton(self)
        self._lock_button.setText(UNLOCK)
        self._lock_button.setCheckable(True)
        self._lock_button.setAutoRaise(True)
        self._lock_button.setToolTip(tr("insp.lock_hint"))
        self._lock_button.toggled.connect(self._on_lock_toggled)
        top.addWidget(self._lock_button)

        self._reset_button = QToolButton(self)
        self._reset_button.setText(RESET)
        self._reset_button.setAutoRaise(True)
        self._reset_button.setToolTip(tr("insp.reset_hint"))
        self._reset_button.clicked.connect(self._on_reset)
        top.addWidget(self._reset_button)

        self._more_button = QToolButton(self)
        self._more_button.setText(MORE)
        self._more_button.setAutoRaise(True)
        self._more_button.setToolTip(tr("insp.range_hint"))
        self._more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more_menu = QMenu(self._more_button)
        self._more_menu.addAction(tr("insp.range"), self._reset_range)
        self._more_button.setMenu(self._more_menu)
        top.addWidget(self._more_button)
        outer.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setTracking(True)
        self._slider.valueChanged.connect(self._on_slider)
        bottom.addWidget(self._slider, 1)

        self._edit = QLineEdit(self)
        self._edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._edit.setFixedWidth(86)
        self._edit.editingFinished.connect(self._on_edit_finished)
        self._edit.installEventFilter(self)
        bottom.addWidget(self._edit)

        self._unit_label = QLabel(tr(self._units.suffix_key(self._kind)))
        self._unit_label.setMinimumWidth(34)
        bottom.addWidget(self._unit_label)
        outer.addLayout(bottom)

        self._update_slider_range()
        self._info_tooltip = install_tooltip(self, self._build_help())

    # ------------------------------------------------------------------ служебное
    def _build_help(self) -> str:
        """HTML-текст подсказки: название, пояснение, диапазон, подсказка по F1."""
        title = tr(self._spec.title_key)
        body = tr(self._spec.help_key)
        unit = tr(self._units.suffix_key(self._kind))
        span = f"{self._units.display(self._minimum, self._kind)} … {self._units.display(self._maximum, self._kind)} {unit}"
        return (
            f"<b>{title}</b><br>{body}<br><br>"
            f"<span style='color:gray;'>{tr('insp.range')}: {span}<br>"
            f"{tr('insp.info')}</span>"
        )

    def _decimals(self) -> int:
        """Точность отображения значения."""
        if self._spec.kind == "int":
            return 0
        return self._units.decimals(self._kind)

    def _update_slider_range(self) -> None:
        """Пересчитывает целочисленный диапазон ползунка."""
        step = self._step if self._step > 0 else 1.0
        low = int(round(self._minimum / step))
        high = int(round(self._maximum / step))
        if high <= low:
            high = low + 1
        self._slider.blockSignals(True)
        self._slider.setRange(low, high)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(max(1, (high - low) // 10))
        self._slider.blockSignals(False)

    def _slider_position(self, value: float) -> int:
        """Позиция ползунка для значения (с ограничением диапазона)."""
        return int(round(value / self._step))

    # ------------------------------------------------------------------ значение
    def value(self) -> float:
        """Текущее значение во внутренних единицах."""
        return self._value

    def set_value(self, value: float, emit: bool = False) -> None:
        """Устанавливает значение (без сигнала по умолчанию)."""
        value = float(value)
        self._value = value
        position = max(self._slider.minimum(), min(self._slider.maximum(), self._slider_position(value)))
        self._slider.blockSignals(True)
        self._slider.setValue(position)
        self._slider.blockSignals(False)
        self._edit.blockSignals(True)
        self._edit.setText(self._units.display(value, self._kind))
        self._edit.blockSignals(False)
        self._set_state_property(self._edit, "outOfRange", False)
        self._edit.setToolTip("")
        if emit:
            self.valueChanged.emit(value)

    def set_locked(self, locked: bool) -> None:
        """Блокирует редактирование (фиксация параметра)."""
        self._locked = bool(locked)
        self._slider.setEnabled(not self._locked)
        self._edit.setEnabled(not self._locked)
        self._reset_button.setEnabled(not self._locked)
        self._lock_button.blockSignals(True)
        self._lock_button.setChecked(self._locked)
        self._lock_button.setText(LOCK if self._locked else UNLOCK)
        self._lock_button.blockSignals(False)

    def is_locked(self) -> bool:
        """Зафиксирован ли параметр."""
        return self._locked

    def _set_state_property(self, widget: QWidget, name: str, value: bool) -> None:
        """Меняет динамическое свойство оформления и перерисовывает виджет."""
        widget.setProperty(name, value)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    # ------------------------------------------------------------------ реакция на ввод
    def _on_slider(self, position: int) -> None:
        """Ползунок: новое значение шагом сетки."""
        if self._locked:
            return
        value = position * self._step
        self._value = value
        self._edit.setText(self._units.display(value, self._kind))
        self.valueChanged.emit(value)

    def _commit_text(self) -> bool:
        """Разбирает текст поля и применяет значение. False — ошибка разбора."""
        text = self._edit.text()
        try:
            value = self._units.parse(text, self._kind)
        except UnitConversionError as error:
            self._reject_input(tr(error.message_key, value=text))
            return False
        # Qt хранит границы ползунка в знаковом 32-битном целом.
        if abs(value / self._step) > 1_000_000_000:
            self._reject_input(tr("error.number.too_large"))
            return False
        if self._spec.kind == "int":
            value = float(round(value))
        self._apply_value(value)
        return True

    def _apply_value(self, value: float) -> None:
        """Применяет введённое значение с учётом границ ползунка."""
        step = self._step if self._step > 0 else 1.0
        low = self._slider.minimum() * step
        high = self._slider.maximum() * step
        if value < low or value > high:
            if self._auto_extend:
                margin = max(abs(value - low), abs(value - high), step * 10.0) * 0.1
                self._minimum = min(self._minimum, value - margin)
                self._maximum = max(self._maximum, value + margin)
                self._update_slider_range()
                self._info_tooltip.set_html(self._build_help())
                self.set_value(value, emit=True)
                return
            self._set_state_property(self._edit, "outOfRange", True)
            self._edit.setToolTip(
                tr(
                    "error.number.out_of_range_slider",
                    min=self._units.display(low, self._kind),
                    max=self._units.display(high, self._kind),
                    new_min=self._units.display(self._minimum, self._kind),
                    new_max=self._units.display(self._maximum, self._kind),
                )
            )
        self.set_value(value, emit=True)

    def _reject_input(self, message: str) -> None:
        """Показывает ошибку ввода и возвращает прежнее значение."""
        self._invalid = True
        self._set_state_property(self._edit, "invalid", True)
        self._edit.setToolTip(message)
        self._edit.setFocus()
        self._edit.selectAll()

    def _on_edit_finished(self) -> None:
        """Завершение ввода: разбор значения и снятие подсветки ошибки."""
        if self._locked:
            return
        parsed = self._commit_text()
        if parsed:
            self._invalid = False
            self._set_state_property(self._edit, "invalid", False)

    # ------------------------------------------------------------------ клавиатура
    def eventFilter(self, watched, event) -> bool:  # noqa: N801 (Qt API)
        """Обрабатывает клавиши и колесо мыши в поле ввода."""
        if watched is not self._edit or self._locked:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.KeyPress:
            key_event: QKeyEvent = event  # type: ignore[assignment]
            if self._handle_key(key_event):
                return True
        elif event.type() == QEvent.Type.Wheel:
            wheel_event: QWheelEvent = event  # type: ignore[assignment]
            self._step_by(self._step if wheel_event.angleDelta().y() > 0 else -self._step)
            return True
        return super().eventFilter(watched, event)

    def _handle_key(self, event: QKeyEvent) -> bool:
        """Обрабатывает стрелки, Home/End и Esc."""
        key = event.key()
        modifiers = event.modifiers()
        step = self._step
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            step *= 10.0
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            step *= 0.1
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._step_by(step if key == Qt.Key.Key_Up else -step)
            return True
        if key == Qt.Key.Key_Home:
            self._commit_value(self._slider.minimum() * self._step)
            return True
        if key == Qt.Key.Key_End:
            self._commit_value(self._slider.maximum() * self._step)
            return True
        if key == Qt.Key.Key_Escape:
            self.set_value(self._value, emit=False)
            return True
        return False

    def _step_by(self, delta: float) -> None:
        """Изменяет значение на ``delta`` (внутренние единицы)."""
        self._commit_value(self._value + delta)

    def _commit_value(self, value: float) -> None:
        """Применяет значение и обновляет поле."""
        self._apply_value(value)

    # ------------------------------------------------------------------ кнопки
    def _on_lock_toggled(self, checked: bool) -> None:
        """Переключатель фиксации."""
        self._lock_button.setText(LOCK if checked else UNLOCK)
        self._locked = checked
        self._slider.setEnabled(not checked)
        self._edit.setEnabled(not checked)
        self._reset_button.setEnabled(not checked)
        self.lockChanged.emit(checked)

    def _on_reset(self) -> None:
        """Сброс к значению по умолчанию."""
        self._apply_value(self._default)

    def _reset_range(self) -> None:
        """Возвращает границы ползунка к исходным значениям из описания."""
        self._minimum = float(self._spec.minimum)
        self._maximum = float(self._spec.maximum)
        self._update_slider_range()
        self.set_value(self._value, emit=False)
        self._info_tooltip.set_html(self._build_help())
