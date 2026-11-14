"""Диалоги приложения: выбор шаблона, снимки настройки."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.powertrain_layout import LAYOUTS, layout_topology_status
from ..i18n import tr
from ..model.entities import Project
from ..model.templates import TemplateInfo, VehicleTemplateOptions, create_vehicle_template, list_templates


class TemplateDialog(QDialog):
    """Окно выбора шаблона проекта."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("empty.template"))
        self.resize(560, 380)
        self._templates: list[TemplateInfo] = list_templates()
        self._list = QListWidget(self)
        for category in ("passenger", "suv"):
            item = QListWidgetItem(tr(f"template.config.{category}"))
            item.setData(Qt.ItemDataRole.UserRole, category)
            self._list.addItem(item)
        for info in self._templates:
            item = QListWidgetItem(tr(info.title_key))
            item.setData(Qt.ItemDataRole.UserRole, info.key)
            item.setToolTip(tr(info.description_key))
            self._list.addItem(item)
        self._list.setCurrentRow(0)

        self._config = QGroupBox(tr("template.config.title"), self)
        self._front = QComboBox(self._config)
        self._rear = QComboBox(self._config)
        self._powertrain = QComboBox(self._config)
        for code in LAYOUTS:
            self._powertrain.addItem(tr(f"powertrain.{code}"), code)
        self._front_drive = QCheckBox(tr("template.config.driven"), self._config)
        self._rear_drive = QCheckBox(tr("template.config.driven"), self._config)
        self._front_drive.setChecked(True)
        form = QFormLayout(self._config)
        form.addRow(tr("param.powertrain_layout.name"), self._powertrain)
        form.addRow(tr("template.config.front"), self._front)
        form.addRow(tr("template.config.front_drive"), self._front_drive)
        form.addRow(tr("template.config.rear"), self._rear)
        form.addRow(tr("template.config.rear_drive"), self._rear_drive)
        self._powertrain_hint = QLabel(self._config)
        self._powertrain_hint.setObjectName("Hint")
        self._powertrain_hint.setWordWrap(True)
        form.addRow(self._powertrain_hint)
        self._powertrain.currentIndexChanged.connect(self._update_powertrain_hint)
        self._front_drive.toggled.connect(self._update_powertrain_hint)
        self._rear_drive.toggled.connect(self._update_powertrain_hint)
        self._rear.currentIndexChanged.connect(self._rear_changed)
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
        layout.addWidget(self._config)
        layout.addWidget(self._description)
        layout.addWidget(buttons)

    def _update_description(self, row: int) -> None:
        """Показывает описание выбранного шаблона."""
        configured = row in (0, 1)
        self._config.setVisible(configured)
        if configured:
            front = ("macpherson_front", "multilink_front", "double_wishbone") if row == 0 else ("multilink_front", "double_wishbone")
            rear = ("multilink_rear", "torsion_beam_rear") if row == 0 else ("multilink_rear", "live_axle_coil")
            self._front.clear()
            self._rear.clear()
            for code in front:
                self._front.addItem(tr(f"type.{code}.name"), code)
            for code in rear:
                self._rear.addItem(tr(f"type.{code}.name"), code)
            self._powertrain.setCurrentIndex(self._powertrain.findData("transverse_front" if row == 0 else "longitudinal_transfer"))
            self._front_drive.setChecked(True)
            self._rear_drive.setChecked(row == 1)
            self._rear_changed()
            self._update_powertrain_hint()
            self._description.setText(tr("template.config.limits"))
        elif 2 <= row < len(self._templates) + 2:
            self._description.setText(tr(self._templates[row - 2].description_key))
        else:
            self._description.setText("")

    def _rear_changed(self) -> None:
        allowed = self._rear.currentData() != "torsion_beam_rear"
        if not allowed:
            self._rear_drive.setChecked(False)
        self._rear_drive.setEnabled(allowed)

    def _update_powertrain_hint(self, *_args: object) -> None:
        status = layout_topology_status(str(self._powertrain.currentData()),
                                        self._front_drive.isChecked(), self._rear_drive.isChecked())
        self._powertrain_hint.setText(tr(f"powertrain.status.{status}"))

    def selected_project(self) -> Project | None:
        row = self._list.currentRow()
        if row not in (0, 1):
            return None
        return create_vehicle_template(VehicleTemplateOptions(
            category="passenger" if row == 0 else "suv",
            front_type=str(self._front.currentData()), rear_type=str(self._rear.currentData()),
            front_driven=self._front_drive.isChecked(), rear_driven=self._rear_drive.isChecked(),
            powertrain_layout=str(self._powertrain.currentData()),
        ))

    def selected_key(self) -> str | None:
        """Ключ выбранного шаблона."""
        item = self._list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None and self._list.currentRow() >= 2 else None


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


class RestoreSnapshotDialog(QDialog):
    """Выбор снимка с явным перечислением области восстановления."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("snapshot_restore.title"))
        self.resize(580, 340)
        self._list = QListWidget(self)
        for index, snapshot in enumerate(project.snapshots):
            self._list.addItem(f"{index + 1}. {snapshot.name}")
        if project.snapshots:
            self._list.setCurrentRow(0)
        notice = QLabel(tr("snapshot_restore.scope"), self)
        notice.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self._restore = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._restore.setText(tr("snapshot_restore.action"))
        self._restore.setEnabled(bool(project.snapshots))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("dialog.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(notice)
        layout.addWidget(self._list, 1)
        layout.addWidget(buttons)

    def selected_index(self) -> int:
        return self._list.currentRow()
