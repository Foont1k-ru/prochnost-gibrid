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
    lines.extend(("", tr("step_inventory.units_notice")))
    if not result.context_units:
        lines.append(tr("step_inventory.units_none"))
    for unit in result.context_units:
        if unit.status == "known" and unit.mm_per_unit is not None:
            lines.append(tr("step_inventory.unit_known", context=unit.context, unit=unit.unit_entity,
                            factor=f"{unit.mm_per_unit:.9g}"))
        else:
            lines.append(tr(f"step_inventory.unit_status.{unit.status}", context=unit.context))
    lines.extend(("", tr("step_inventory.products")))
    for product in result.products:
        lines.append(f"#{product.entity}: {product.name or tr('step_inventory.unnamed')} ({product.identifier})")
    lines.extend(("", tr("step_inventory.links")))
    frames_by_occurrence = {item.occurrence: item for item in result.placement_frames}
    lines.append(tr("step_inventory.frames_notice"))
    lines.append(tr("step_inventory.rep_notice"))
    if result.placement_limit:
        lines.append(tr("step_inventory.frames_limit"))
    else:
        success = sum(frame.issue is None for frame in result.placement_frames)
        lines.append(tr("step_inventory.frames_summary", count=success,
                        total=len(result.placement_frames), unavailable=len(result.placement_frames) - success))
    for occurrence in result.occurrences:
        parent = _product_name(occurrence.parent, occurrence.parent_definition)
        child = _product_name(occurrence.child, occurrence.child_definition)
        lines.append(f"#{occurrence.entity}: {parent} → {child} ({occurrence.name or occurrence.identifier})")
        placement = frames_by_occurrence.get(occurrence.entity)
        if placement is None:
            continue
        match = placement.representation_match
        if match is not None:
            def label(number):
                return f"#{number}" if number is not None else tr("step_inventory.unknown")
            def membership(value):
                return tr("step_inventory.member." + ("unknown" if value is None else "yes" if value else "no"))
            lines.append("    " + tr(f"step_inventory.rep_status.{match.status}"))
            lines.append("    " + tr("step_inventory.rep_detail", rep1=label(match.representation_1),
                                     rep2=label(match.representation_2), def1=label(match.definition_1),
                                     def2=label(match.definition_2), context1=label(match.context_1),
                                     context2=label(match.context_2)))
            lines.append("    " + tr("step_inventory.rep_members", a1=membership(match.frame_1_membership[0]),
                                     a2=membership(match.frame_1_membership[1]),
                                     b1=membership(match.frame_2_membership[0]),
                                     b2=membership(match.frame_2_membership[1])))
        if placement.issue:
            lines.append("    " + tr(f"step_inventory.frame_issue.{placement.issue}"))
            continue
        lines.append("    " + tr("step_inventory.frame_links", relation=placement.relation,
                                 transformation=placement.transformation))
        for index, frame in enumerate((placement.first, placement.second), 1):
            if frame is not None:
                def fmt(vector):
                    return ", ".join(f"{value:.6g}" for value in vector)
                lines.append("    " + tr("step_inventory.frame", index=index, entity=frame.entity,
                                         origin=fmt(frame.origin), x=fmt(frame.x), y=fmt(frame.y), z=fmt(frame.z)))
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
