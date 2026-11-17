"""Экспериментальный эскиз одной задней трубы; опоры пока не спроектированы."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..model.entities import Project
from ..model.kim_format import KimFormatError, write_document
from ..model.niva_arm_views import REAR, make_niva_arm_view
from ..model.rear_tube import make_rear_tube, rear_tube_centerline
from .controller import AppController
from .niva_arms_dialog import ArmPlan
from .weldment_3d import Weldment3D


class RearTubeDialog(QDialog):
    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._candidate: dict[str, Any] | None = None
        self._revision = 0
        self._closing_confirmed = False
        self._saved_candidate: dict[str, Any] | None = None
        self._baseline: tuple[Any, ...] | None = None
        self.setWindowTitle(tr('rear_tube.title'))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(800, 790)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget(scroll)
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        warning = QLabel(tr('rear_tube.warning'), body)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        self._arm = QComboBox(body)
        for key in REAR:
            self._arm.addItem(tr(f'niva_arms.{key}'), key)
        form.addRow(tr('niva_arms.choose'), self._arm)
        self._radius = self._spin(body, 12.)
        self._wall = self._spin(body, 2.)
        form.addRow(tr('arm_concept.radius'), self._radius)
        form.addRow(tr('arm_concept.wall'), self._wall)
        self._bend = QCheckBox(tr('rear_tube.bend'), body)
        form.addRow(self._bend)
        row = QHBoxLayout()
        self._fields: list[QLineEdit] = []
        for key in ('x', 'y', 'z', 'r'):
            field = QLineEdit(body)
            field.setPlaceholderText(tr(f'arm_concept.bend_{key}'))
            field.setAccessibleName(tr('rear_tube.bend') + ' ' + tr(f'arm_concept.bend_{key}'))
            field.setMaxLength(64)
            row.addWidget(field)
            self._fields.append(field)
        form.addRow(row)
        layout.addLayout(form)
        note = QLabel(tr('rear_tube.bend_note'), body)
        note.setWordWrap(True)
        layout.addWidget(note)
        self._status = QLabel(body)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._edit_status = QLabel(body)
        self._edit_status.setWordWrap(True)
        layout.addWidget(self._edit_status)
        tabs = QTabWidget(body)
        self._plans = [ArmPlan(axes, tabs) for axes in ((0, 1), (0, 2), (1, 2))]
        for plan, label in zip(self._plans, ('XY', 'XZ', 'YZ'), strict=True):
            tabs.addTab(plan, label)
        self._three_d = Weldment3D(tabs, is_current=self._candidate_is_current, single_tube=True)
        tabs.addTab(self._three_d, tr('rear_tube.tab_3d'))
        layout.addWidget(tabs, 1)
        self._save = QPushButton(tr('rear_tube.save'), body)
        self._save.clicked.connect(self._save_copy)
        layout.addWidget(self._save)
        self._saved = QLabel(body)
        self._saved.setWordWrap(True)
        self._saved.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._saved)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, body)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._arm.currentIndexChanged.connect(self._refresh)
        self._radius.valueChanged.connect(self._refresh)
        self._wall.valueChanged.connect(self._refresh)
        self._bend.toggled.connect(self._refresh)
        for field in self._fields:
            field.textChanged.connect(self._refresh)
        self._three_d.availabilityChanged.connect(self._update_save)
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._refresh)
        self._refresh()
        self._baseline = self._input_state()
        self._update_edit_status()

    @staticmethod
    def _spin(parent: QWidget, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(parent)
        spin.setRange(0.01, 10000.)
        spin.setDecimals(2)
        spin.setValue(value)
        spin.setSuffix(' mm')
        spin.setKeyboardTracking(False)
        return spin

    def _make_candidate(self) -> dict[str, Any]:
        bend = None
        if self._bend.isChecked():
            try:
                numbers = [float(field.text().strip().replace(',', '.')) for field in self._fields]
            except ValueError as error:
                raise KimFormatError('all bend inputs are required') from error
            bend = {'vertex_mm': numbers[:3], 'radius_mm': numbers[3]}
        return make_rear_tube(self.controller.project, str(self._arm.currentData()),
                              self._radius.value(), self._wall.value(), bend)

    def _refresh(self, *_args: object) -> None:
        self._revision += 1
        self._saved.clear()
        self._candidate = None
        for field in self._fields:
            field.setEnabled(self._bend.isChecked())
        for plan in self._plans:
            plan.set_view(None)
        self._three_d.set_document(None)
        self._update_save()
        try:
            candidate = self._make_candidate()
            path = rear_tube_centerline(candidate)
            view = make_niva_arm_view(Project.from_dict(candidate['scheme']), candidate['arm'])
        except (KimFormatError, ValueError, TypeError, OverflowError):
            self._status.setText(tr('rear_tube.invalid'))
            self._update_edit_status()
            return
        self._candidate = candidate
        for plan in self._plans:
            plan.set_view(view, path)
        self._three_d.set_document(candidate)
        self._status.setText(tr('rear_tube.ready'))
        self._update_save()
        self._update_edit_status()

    def _input_state(self) -> tuple[Any, ...]:
        return (self._arm.currentData(), self._radius.value(), self._wall.value(), self._bend.isChecked(),
                tuple(field.text() for field in self._fields) if self._bend.isChecked() else ())

    def _has_unsaved(self) -> bool:
        return (self._baseline is not None and (self._input_state() != self._baseline or
                (self._saved_candidate is not None and self._saved_candidate != self._candidate)))

    def _update_edit_status(self) -> None:
        self._edit_status.setText(tr("rear_tube.unsaved") if self._has_unsaved() else "")

    def confirm_close(self) -> bool:
        if self._closing_confirmed or not self._has_unsaved():
            return True
        state, revision = self._input_state(), self._revision
        answer = QMessageBox.question(self, tr("weldment.discard_title"), tr("rear_tube.discard"),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return (answer == QMessageBox.StandardButton.Yes and state == self._input_state() and
                revision == self._revision)

    def _candidate_is_current(self, candidate: dict[str, Any]) -> bool:
        if candidate != self._candidate:
            return False
        try:
            return self._make_candidate() == candidate
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def _update_save(self, *_args: object) -> None:
        self._save.setEnabled(self._candidate is not None and self._three_d.can_save())

    def _save_copy(self) -> None:
        candidate = self._candidate
        if candidate is None or not self._three_d.can_save():
            return
        revision, generation = self._revision, self._three_d.generation
        selected, _ = QFileDialog.getSaveFileName(self, tr('rear_tube.save'), '', tr('arm_concept.assembly_filter'))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kima':
            path = path.with_name(path.name + '.kima')
        if (revision != self._revision or generation != self._three_d.generation or not self._three_d.can_save()):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.changed'))
            return
        try:
            if not self._candidate_is_current(candidate):
                raise KimFormatError('inputs changed')
            if self.controller.is_protected_export_target(path):
                raise KimFormatError('protected project')
            write_document(path, 'assembly', candidate, overwrite=False)
        except (KimFormatError, OSError, ValueError, TypeError, RuntimeError):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.save_failed'))
            self._refresh()
            return
        self._baseline = self._input_state()
        self._saved_candidate = candidate
        self._update_edit_status()
        self._saved.setText(tr('weldment.saved', path=str(path)))

    def shutdown(self) -> bool:
        return self._three_d.shutdown()

    def reject(self) -> None:
        if self.confirm_close() and self.shutdown():
            super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.confirm_close() or not self.shutdown():
            event.ignore()
            return
        self._closing_confirmed = True
        try:
            super().closeEvent(event)
        finally:
            self._closing_confirmed = False
