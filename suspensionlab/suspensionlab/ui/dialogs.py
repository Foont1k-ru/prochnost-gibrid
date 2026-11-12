"""Диалоги приложения: выбор шаблона, снимки настройки."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..model.templates import TemplateInfo, list_templates


class TemplateDialog(QDialog):
    """Окно выбора шаблона проекта."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("empty.template"))
        self.resize(560, 380)
        self._templates: list[TemplateInfo] = list_templates()
        self._list = QListWidget(self)
        for info in self._templates:
            item = QListWidgetItem(tr(info.title_key))
            item.setData(Qt.ItemDataRole.UserRole, info.key)
            item.setToolTip(tr(info.description_key))
            self._list.addItem(item)
        if self._templates:
            self._list.setCurrentRow(0)

        self._description = QLabel(self)
        self._description.setObjectName("Hint")
        self._description.setWordWrap(True)
        self._list.currentRowChanged.connect(self._update_description)
        self._update_description(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("empty.template"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("dialog.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("empty.subtitle")))
        layout.addWidget(self._list, 1)
        layout.addWidget(self._description)
        layout.addWidget(buttons)

    def _update_description(self, row: int) -> None:
        """Показывает описание выбранного шаблона."""
        if 0 <= row < len(self._templates):
            self._description.setText(tr(self._templates[row].description_key))
        else:
            self._description.setText("")

    def selected_key(self) -> str | None:
        """Ключ выбранного шаблона."""
        item = self._list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None


class SnapshotDialog(QDialog):
    """Запрос имени снимка настройки."""

    def __init__(self, default_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.save_snapshot"))
        self.resize(420, 140)
        self._edit = QLineEdit(default_name, self)
        self._edit.selectAll()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("dialog.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("dialog.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("dialog.snapshot_text")))
        layout.addWidget(self._edit)
        layout.addWidget(buttons)

    def name(self) -> str:
        """Введённое имя снимка."""
        return self._edit.text().strip()
