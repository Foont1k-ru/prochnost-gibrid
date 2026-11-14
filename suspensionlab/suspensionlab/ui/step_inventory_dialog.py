"""Локальный обзор имён и связей STEP, не импорт геометрии."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from ..core.step_inventory import StepInventory, StepInventoryError, read_step_inventory
from ..i18n import tr

LOG = logging.getLogger(__name__)


class _Reader(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path, parent: QDialog) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        try:
            self.result_ready.emit(read_step_inventory(self._path))
        except StepInventoryError as error:
            self.failed.emit(str(error))
        except Exception:
            LOG.exception("Неожиданная ошибка обзора STEP")
            self.failed.emit(tr("step_inventory.unexpected"))


def _product_name(product, definition: int) -> str:
    if product is None:
        return tr("step_inventory.unresolved", entity=definition)
    return f"{product.name or product.identifier or tr('step_inventory.unnamed')} [#{definition}]"


def inventory_text(result: StepInventory) -> str:
    lines = [tr("step_inventory.summary", schema=", ".join(result.schema) or tr("step_inventory.unknown"),
                products=len(result.products), definitions=result.definitions, occurrences=len(result.occurrences),
                unresolved=result.unresolved_occurrences, solids=result.solid_records,
                transforms=result.transformation_records)]
    if result.non_ascii_bytes:
        lines.append(tr("step_inventory.non_ascii"))
    if result.unsupported_string_escape:
        lines.append(tr("step_inventory.string_escape"))
    lines.extend(("", tr("step_inventory.products")))
    for product in result.products:
        lines.append(f"#{product.entity}: {product.name or tr('step_inventory.unnamed')} ({product.identifier})")
    lines.extend(("", tr("step_inventory.links")))
    for occurrence in result.occurrences:
        parent = _product_name(occurrence.parent, occurrence.parent_definition)
        child = _product_name(occurrence.child, occurrence.child_definition)
        lines.append(f"#{occurrence.entity}: {parent} → {child} ({occurrence.name or occurrence.identifier})")
    return "\n".join(lines)


class StepInventoryDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("step_inventory.title"))
        self.resize(850, 650)
        self._reader: _Reader | None = None
        layout = QVBoxLayout(self)
        notice = QLabel(tr("step_inventory.notice"), self)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self._choose = QPushButton(tr("step_inventory.choose"), self)
        self._choose.clicked.connect(self._choose_file)
        layout.addWidget(self._choose)
        self._status = QLabel(tr("step_inventory.empty"), self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._text = QPlainTextEdit(self)
        self._text.setReadOnly(True)
        layout.addWidget(self._text, 1)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("step_inventory.choose"), "", tr("step_inventory.filter"))
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path) -> None:
        if self._reader is not None:
            return
        self._text.clear()
        self._status.setText(tr("step_inventory.loading"))
        self._choose.setEnabled(False)
        self._buttons.setEnabled(False)
        reader = _Reader(path, self)
        self._reader = reader
        reader.result_ready.connect(self._show_result)
        reader.failed.connect(self._show_error)
        reader.finished.connect(self._finished)
        reader.start()

    def _show_result(self, result: StepInventory) -> None:
        self._text.setPlainText(inventory_text(result))
        self._status.setText(tr("step_inventory.done"))

    def _show_error(self, error: str) -> None:
        self._text.clear()
        self._status.setText(tr("step_inventory.error", reason=error))

    def _finished(self) -> None:
        reader = self._reader
        self._reader = None
        if reader is not None:
            reader.deleteLater()
        self._choose.setEnabled(True)
        self._buttons.setEnabled(True)

    def reject(self) -> None:
        if self._reader is None:
            super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._reader is not None:
            event.ignore()
        else:
            super().closeEvent(event)
