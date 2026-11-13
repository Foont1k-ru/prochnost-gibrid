"""Покадровое проигрывание рассчитанной сетки, не симуляция времени."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from ...i18n import tr


class PlaybackControls(QWidget):
    """Следующая строка показывается лишь при отсутствии обнаруженного конфликта."""

    def __init__(self, current: Callable[[], int], select: Callable[[int], None],
                 problem: Callable[[int], str | None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current, self._select, self._problem = current, select, problem
        self._count = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.advance)
        self._button = QPushButton(tr("playback.play"), self)
        self._button.clicked.connect(self.toggle)
        self._fps = QSpinBox(self)
        self._fps.setRange(1, 30)
        self._fps.setValue(5)
        self._fps.valueChanged.connect(self._set_interval)
        self._message = QLabel(tr("playback.notice"), self)
        self._message.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self._button)
        row.addWidget(QLabel(tr("playback.fps"), self))
        row.addWidget(self._fps)
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self._message)
        self._set_interval()
        self.set_count(0)

    def _set_interval(self, *_args: object) -> None:
        self._timer.setInterval(max(1, round(1000 / self._fps.value())))

    def set_count(self, count: int) -> None:
        self._count = count
        self.stop()
        self._button.setEnabled(count > 1)
        self._message.setText(tr("playback.notice"))

    def stop(self, reason: str | None = None) -> None:
        self._timer.stop()
        self._button.setText(tr("playback.play"))
        if reason is not None:
            self._message.setText(tr("playback.stopped", reason=reason))

    def toggle(self) -> None:
        if self._timer.isActive():
            self.stop(tr("playback.paused"))
            return
        row = self._current()
        if not 0 <= row < self._count:
            self.stop(tr("playback.no_selection"))
            return
        problem = self._problem(row)
        if problem is not None:
            self.stop(problem)
            return
        if row == self._count - 1:
            self.stop(tr("playback.end"))
            return
        self._message.setText(tr("playback.playing"))
        self._button.setText(tr("playback.pause"))
        self._timer.start()

    def advance(self) -> None:
        if not self._timer.isActive():
            return
        row = self._current()
        if not 0 <= row < self._count:
            self.stop(tr("playback.no_selection"))
            return
        # Повторно проверяем текущую строку, если пользователь изменил выбор.
        problem = self._problem(row)
        if problem is not None:
            self.stop(problem)
            return
        next_row = row + 1
        if next_row >= self._count:
            self.stop(tr("playback.end"))
            return
        problem = self._problem(next_row)
        if problem is not None:
            self.stop(problem)
            return
        self._select(next_row)
        if next_row == self._count - 1:
            self.stop(tr("playback.end"))

    def observe_row(self, row: int) -> None:
        """Ручной выбор во время проигрывания не обходит проверку строки."""
        if self._timer.isActive():
            problem = self._problem(row) if 0 <= row < self._count else tr("playback.no_selection")
            if problem is not None:
                self.stop(problem)
            elif row == self._count - 1:
                self.stop(tr("playback.end"))
