"""Экспериментальный эскиз одной задней трубы; опоры пока не спроектированы."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
from ..model.autosave_guard import same_project_file
from ..model.entities import Project
from ..model.kim_format import KimFormatError, read_document, write_document
from ..model.niva_arm_views import REAR, make_niva_arm_view
from ..model.rear_tube import make_rear_tube, rear_tube_centerline, rear_tube_points, validate_rear_tube
from .controller import AppController
from .niva_arms_dialog import ArmPlan
from .weldment_3d import Weldment3D


class RearTubeDialog(QDialog):
    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._candidate: dict[str, Any] | None = None
        self._source: dict[str, Any] | None = None
        self._source_paths: tuple[Path, ...] = ()
        self._active = True
        self._pending_project_changes = False
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
        self._new = QPushButton(tr('rear_tube.new_button'), body)
        self._new.clicked.connect(self._new_draft)
        layout.addWidget(self._new)
        self._open = QPushButton(tr('rear_tube.open'), body)
        self._open.clicked.connect(self._open_file)
        layout.addWidget(self._open)
        self._source_label = QLabel(tr('rear_tube.new'), body)
        self._source_label.setWordWrap(True)
        self._source_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._source_label)
        self._activate = QPushButton(tr('rear_tube.activate'), body)
        self._activate.clicked.connect(self._start_preview)
        self._activate.setVisible(False)
        layout.addWidget(self._activate)
        form = QFormLayout()
        self._arm = QComboBox(body)
        for key in REAR:
            self._arm.addItem(tr(f'niva_arms.{key}'), key)
        form.addRow(tr('niva_arms.choose'), self._arm)
        self._radius = self._number_field(body, '12', tr('rear_tube.radius'))
        self._wall = self._number_field(body, '2', tr('rear_tube.wall'))
        form.addRow(tr('rear_tube.radius'), self._radius)
        form.addRow(tr('rear_tube.wall'), self._wall)
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
        self._radius.textChanged.connect(self._refresh)
        self._wall.textChanged.connect(self._refresh)
        self._bend.toggled.connect(self._refresh)
        for field in self._fields:
            field.textChanged.connect(self._refresh)
        self._three_d.availabilityChanged.connect(self._update_save)
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._project_replaced)
        self._refresh()
        self._baseline = self._input_state()
        self._update_edit_status()

    @staticmethod
    def _number_field(parent: QWidget, value: str, label: str) -> QLineEdit:
        field = QLineEdit(value, parent)
        field.setMaxLength(64)
        field.setAccessibleName(label)
        return field

    def _new_draft(self) -> None:
        if not self.confirm_close():
            return
        self._source, self._source_paths, self._active = None, (), True
        self._saved_candidate = None
        self._pending_project_changes = False
        widgets = [self._arm, self._radius, self._wall, self._bend, *self._fields]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self._arm.setCurrentIndex(0)
            self._radius.setText('12')
            self._wall.setText('2')
            self._bend.setChecked(False)
            for field in self._fields:
                field.clear()
        finally:
            for blocker in blockers:
                blocker.unblock()
        self._source_label.setText(tr('rear_tube.new'))
        self._baseline = self._input_state()
        self._refresh()

    def _open_file(self) -> None:
        revision, state = self._revision, self._input_state()
        selected, _ = QFileDialog.getOpenFileName(self, tr('rear_tube.open'), '', tr('arm_concept.assembly_filter'))
        if not selected:
            return
        if revision != self._revision or state != self._input_state():
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.changed'))
            return
        try:
            path = Path(selected).absolute()
            resolved = path.resolve()
            document = read_document(path, 'assembly')
            validate_rear_tube(document)
        except (KimFormatError, OSError, ValueError, RuntimeError):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('rear_tube.open_failed'))
            return
        if not self.confirm_close():
            return
        # Do not let changes made in a nested confirmation replace new work.
        if revision != self._revision or state != self._input_state():
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.changed'))
            return
        self._source, self._source_paths, self._active = document, (path, resolved), False
        self._pending_project_changes = False
        widgets = [self._arm, self._radius, self._wall, self._bend, *self._fields]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self._arm.setCurrentIndex(self._arm.findData(document['arm']))
            self._radius.setText(str(document['radius_mm']))
            self._wall.setText(str(document['wall_mm']))
            bend = document['bend']
            self._bend.setChecked(bend is not None)
            values = [*bend['vertex_mm'], bend['radius_mm']] if bend is not None else ['', '', '', '']
            for field, value in zip(self._fields, values, strict=True):
                field.setText(str(value))
        finally:
            for blocker in blockers:
                blocker.unblock()
        self._source_label.setText(tr('rear_tube.source', path=str(path), name=document['name']))
        self._baseline = self._input_state()
        self._saved_candidate = document
        self._refresh()

    def _start_preview(self) -> None:
        if self._source is None:
            return
        self._active = True
        self._refresh()

    def _project_replaced(self) -> None:
        if self._source is not None:
            self._pending_project_changes = self._pending_project_changes or (
                self._active and self._saved_candidate is not None and self._saved_candidate != self._candidate)
            self._active = False
        self._refresh()

    def _make_candidate(self) -> dict[str, Any]:
        bend = None
        if self._bend.isChecked():
            try:
                numbers = [float(field.text().strip().replace(',', '.')) for field in self._fields]
            except ValueError as error:
                raise KimFormatError('all bend inputs are required') from error
            bend = {'vertex_mm': numbers[:3], 'radius_mm': numbers[3]}
        try:
            radius = float(self._radius.text().strip().replace(',', '.'))
            wall = float(self._wall.text().strip().replace(',', '.'))
        except ValueError as error:
            raise KimFormatError('tube dimensions are required') from error
        result = make_rear_tube(self.controller.project, str(self._arm.currentData()), radius, wall, bend)
        if self._source is not None:
            result['name'] = self._source['name']
        return result

    def _refresh(self, *_args: object) -> None:
        self._revision += 1
        self._saved.clear()
        self._candidate = None
        for widget in (self._arm, self._radius, self._wall, self._bend):
            widget.setEnabled(self._active)
        for field in self._fields:
            field.setEnabled(self._active and self._bend.isChecked())
        self._activate.setVisible(self._source is not None)
        self._activate.setEnabled(self._source is not None and not self._active)
        for plan in self._plans:
            plan.set_view(None)
        self._three_d.set_document(None)
        self._update_save()
        try:
            candidate = self._source if self._source is not None and not self._active else self._make_candidate()
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
        if self._source is not None and not self._active:
            self._status.setText(tr('rear_tube.snapshot'))
        elif self._source is not None:
            matches = (self._source['arm'] == candidate['arm'] and
                       rear_tube_points(self._source) == rear_tube_points(candidate))
            self._status.setText(tr('rear_tube.match' if matches else 'rear_tube.different'))
        else:
            self._status.setText(tr('rear_tube.ready'))
        self._update_save()
        self._update_edit_status()

    def _input_state(self) -> tuple[Any, ...]:
        return (self._arm.currentData(), self._radius.text(), self._wall.text(), self._bend.isChecked(),
                tuple(field.text() for field in self._fields) if self._bend.isChecked() else ())

    def _has_unsaved(self) -> bool:
        return (self._baseline is not None and (self._input_state() != self._baseline or
                self._pending_project_changes or (self._active and self._saved_candidate is not None and
                                                  self._saved_candidate != self._candidate)))

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
        if self._source is not None and not self._active:
            return candidate == self._source
        try:
            return self._make_candidate() == candidate
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def _update_save(self, *_args: object) -> None:
        self._save.setEnabled(self._active and self._candidate is not None and self._three_d.can_save())

    def _save_copy(self) -> None:
        candidate = self._candidate
        if not self._active or candidate is None or not self._three_d.can_save():
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
            if any(same_project_file(path, source) for source in self._source_paths):
                raise KimFormatError('original source path')
            if self.controller.is_protected_export_target(path):
                raise KimFormatError('protected project')
            write_document(path, 'assembly', candidate, overwrite=False)
        except (KimFormatError, OSError, ValueError, TypeError, RuntimeError):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.save_failed'))
            self._refresh()
            return
        self._baseline = self._input_state()
        self._saved_candidate = candidate
        self._pending_project_changes = False
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
