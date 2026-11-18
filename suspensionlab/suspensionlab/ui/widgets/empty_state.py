"""Пустое состояние: что делать, когда проект ещё не начат.

По ТЗ (§6.10) вместо пустого экрана пользователь видит три понятных
действия: шаблон, открытие файла и создание проекта с нуля.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...i18n import tr


class EmptyState(QWidget):
    """Карточки быстрого старта."""

    newRequested = Signal()
    openRequested = Signal()
    templateRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame = QFrame(self)
        frame.setObjectName("EmptyState")
        frame.setMaximumWidth(760)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        title = QLabel(tr("empty.title"))
        title.setObjectName("EmptyTitle")
        layout.addWidget(title)

        subtitle = QLabel(tr("empty.subtitle"))
        subtitle.setObjectName("EmptySubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        cards.addWidget(self._card("empty.new", "empty.new_hint", self.newRequested))
        cards.addWidget(self._card("empty.open", "empty.open_hint", self.openRequested))
        cards.addWidget(self._card("empty.template", "empty.template_hint", self.templateRequested))
        layout.addLayout(cards)

        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(frame)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

    def _card(self, title_key: str, hint_key: str, signal) -> QWidget:
        """Карточка действия с кнопкой."""
        card = QFrame()
        card.setObjectName("Section")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        title = QLabel(tr(title_key))
        title.setStyleSheet("font-weight:600; font-size:14px;")
        layout.addWidget(title)
        hint = QLabel(tr(hint_key))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        button = QPushButton(tr(title_key))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(signal.emit)
        layout.addWidget(button)
        return card
