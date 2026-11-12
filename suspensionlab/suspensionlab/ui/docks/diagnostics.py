"""Панель диагностики: проверки модели с понятными русскими текстами.

Каждое сообщение кликабельно: нажатие выбирает «виновника» в дереве
проекта и на схеме. Сообщения сортируются по важности.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ...i18n import tr
from ...model.validation import Issue, count_by_severity
from ..controller import AppController, Selection
from ..widgets.glyphs import STATUS_ERROR, STATUS_OK, STATUS_WARN

_ICONS = {"error": STATUS_ERROR, "warning": STATUS_WARN, "info": "·"}


class DiagnosticsPanel(QWidget):
    """Список сообщений диагностики текущего проекта."""

    issueSelected = Signal(object)

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._list = QListWidget(self)
        self._list.setAlternatingRowColors(True)
        self._list.setUniformItemSizes(False)
        self._list.itemActivated.connect(self._on_item)
        self._list.itemClicked.connect(self._on_item)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)

        controller.modelChanged.connect(self.refresh)
        controller.projectReplaced.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Перестраивает список сообщений."""
        self._list.clear()
        issues = self._controller.issues
        if not issues:
            item = QListWidgetItem(f"{STATUS_OK}  {tr('diag.empty')}")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            return
        for issue in issues:
            icon = _ICONS.get(issue.severity, "·")
            text = tr(issue.key, **issue.text_params())
            role = f"[{tr('canvas.front') if issue.role == 'front' else tr('canvas.rear')}] " if issue.role else ""
            item = QListWidgetItem(f"{icon}  {role}{text}")
            item.setData(0x0100, issue)
            item.setToolTip(text)
            self._list.addItem(item)

    def _on_item(self, item: QListWidgetItem) -> None:
        """Выбор сообщения: подсветка связанного элемента модели."""
        issue = item.data(0x0100)
        if not isinstance(issue, Issue):
            return
        if issue.code and issue.role:
            kind = "point" if issue.key in ("diag.point_missing", "diag.points_coincide", "diag.point_out_of_zone", "diag.point_below_ground") else "link"
            self.issueSelected.emit(Selection(kind, issue.role, issue.code))
        elif issue.role:
            self.issueSelected.emit(Selection("axle", issue.role))

    def counts(self) -> dict[str, int]:
        """Счётчики сообщений по важности (для заголовка вкладки)."""
        return count_by_severity(self._controller.issues)
