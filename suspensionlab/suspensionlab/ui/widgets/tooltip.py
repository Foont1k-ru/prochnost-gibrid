"""Богатые подсказки с управляемой задержкой появления.

Стандартный QToolTip показывается примерно через 0,7 с и не позволяет
задать задержку. По ТЗ (§6.4) подсказка должна появляться через
350–500 мс, поэтому используется собственный таймер.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import QToolTip, QWidget

#: Задержка появления подсказки, мс.
TOOLTIP_DELAY_MS = 420


class RichTooltip(QObject):
    """Показывает HTML-подсказку у курсора после небольшой задержки."""

    def __init__(self, widget: QWidget, html: str) -> None:
        super().__init__(widget)
        self._widget = widget
        self._html = html
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(TOOLTIP_DELAY_MS)
        self._timer.timeout.connect(self._show)
        widget.installEventFilter(self)

    def set_html(self, html: str) -> None:
        """Обновляет текст подсказки."""
        self._html = html

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Запускает таймер при входе курсора и скрывает подсказку при уходе."""
        if event.type() == QEvent.Type.Enter:
            self._timer.start()
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide):
            self._timer.stop()
            QToolTip.hideText()
        return False

    def _show(self) -> None:
        """Показывает подсказку рядом с курсором."""
        if not self._widget.isVisible():
            return
        position: QPoint = self._widget.cursor().pos()
        QToolTip.showText(position, self._html, self._widget)


def install_tooltip(widget: QWidget, html: str) -> RichTooltip:
    """Удобная обёртка: вешает подсказку и возвращает объект для обновления."""
    widget.setToolTip(html)
    return RichTooltip(widget, html)
