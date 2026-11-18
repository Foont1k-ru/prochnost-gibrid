"""Общий ввод одного опционального изгиба на каждую из двух труб."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..i18n import tr
from ..model.kim_format import KimFormatError


class BendEditor(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.checks: dict[str, QCheckBox] = {}
        self.fields: dict[str, list[QLineEdit]] = {}
        self._editable = True
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        for leg in ("front", "rear"):
            row = QHBoxLayout()
            check = QCheckBox(tr(f"arm_concept.bend_{leg}"), self)
            row.addWidget(check)
            fields = []
            for key in ("x", "y", "z", "r"):
                field = QLineEdit(self)
                field.setPlaceholderText(tr(f"arm_concept.bend_{key}"))
                field.setAccessibleName(tr(f"arm_concept.bend_{leg}") + " " + tr(f"arm_concept.bend_{key}"))
                field.setMaxLength(64)
                row.addWidget(field)
                fields.append(field)
                field.textChanged.connect(self._changed)
            self.checks[leg] = check
            self.fields[leg] = fields
            check.toggled.connect(self._changed)
            form.addRow(row)
        layout.addLayout(form)
        note = QLabel(tr("arm_concept.bend_note"), self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self._update_enabled()

    def _update_enabled(self) -> None:
        for leg, check in self.checks.items():
            check.setEnabled(self._editable)
            for field in self.fields[leg]:
                field.setEnabled(self._editable and check.isChecked())

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        self._update_enabled()

    def _changed(self, *_args: object) -> None:
        self._update_enabled()
        if not self._loading:
            self.changed.emit()

    def load(self, bends: dict[str, dict[str, Any]]) -> None:
        """Никакого округления или вымышленных значений для прямой трубы."""
        self._loading = True
        try:
            for leg, check in self.checks.items():
                bend = bends.get(leg)
                values = [*bend["vertex_mm"], bend["radius_mm"]] if bend is not None else ["", "", "", ""]
                for field, value in zip(self.fields[leg], values, strict=True):
                    field.setText(str(value))
                check.setChecked(bend is not None)
        finally:
            self._loading = False
            self._update_enabled()

    def has_bends(self) -> bool:
        return any(check.isChecked() for check in self.checks.values())

    def values(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for leg, check in self.checks.items():
            if not check.isChecked():
                continue
            try:
                numbers = [float(field.text().strip().replace(",", ".")) for field in self.fields[leg]]
            except ValueError as error:
                raise KimFormatError("all bend inputs are required") from error
            result[leg] = {"vertex_mm": numbers[:3], "radius_mm": numbers[3]}
        return result

    def state(self) -> tuple[tuple[bool, tuple[str, ...]], ...]:
        """Только включённые значения попадут в сохраняемую копию."""
        return tuple((check.isChecked(), tuple(field.text() for field in self.fields[leg]) if check.isChecked() else ())
                     for leg, check in self.checks.items())
