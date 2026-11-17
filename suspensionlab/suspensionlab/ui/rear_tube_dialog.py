"""Экспериментальный эскиз одной задней трубы; опоры пока не спроектированы."""
from __future__ import annotations

import copy
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
from ..model.joint_concept import validate_joint_concept
from ..model.kim_format import KimFormatError, read_document, write_document
from ..model.niva_arm_views import REAR, make_niva_arm_view
from ..model.rear_joint_layout import AXES, make_rear_joint_layout, validate_rear_joint_layout
from ..model.rear_pair_snapshot import make_rear_pair_snapshot, rear_pair_sides
from ..model.rear_tube import make_rear_tube, rear_tube_centerline, rear_tube_points, validate_rear_tube
from ..model.rear_tube_pair import PAIRS, make_paired_rear_tube
from .controller import AppController
from .niva_arms_dialog import ArmPlan
from .weldment_3d import Weldment3D


class RearTubeDialog(QDialog):
    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._candidate: dict[str, Any] | None = None
        self._source: dict[str, Any] | None = None
        self._source_pair: dict[str, Any] | None = None
        self._saved_pair: dict[str, Any] | None = None
        self._saved_layout: dict[str, Any] | None = None
        self._joint_doc: dict[str, Any] | None = None
        self._joint_paths: tuple[Path, ...] = ()
        self._joint_baseline: tuple[Any, ...] | None = None
        self._pair_baseline: tuple[Any, ...] | None = None
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
        pair_note = QLabel(tr('rear_pair.note'), body)
        pair_note.setWordWrap(True)
        layout.addWidget(pair_note)
        pair_form = QFormLayout()
        self._pair_mode = QComboBox(body)
        self._pair_mode.addItem(tr('rear_pair.choose'), '')
        self._pair_mode.addItem(tr('rear_pair.same'), 'same')
        self._pair_mode.addItem(tr('rear_pair.mirror'), 'mirror')
        self._pair_roll = self._number_field(body, '0', tr('rear_pair.roll'))
        pair_form.addRow(tr('rear_pair.mode'), self._pair_mode)
        pair_form.addRow(tr('rear_pair.roll'), self._pair_roll)
        layout.addLayout(pair_form)
        self._pair = QPushButton(tr('rear_pair.apply'), body)
        self._pair.clicked.connect(self._apply_pair)
        layout.addWidget(self._pair)
        layout_note = QLabel(tr('rear_joint_layout.note'), body)
        layout_note.setWordWrap(True)
        layout.addWidget(layout_note)
        self._joint_load = QPushButton(tr('rear_joint_layout.load'), body)
        self._joint_load.clicked.connect(self._load_joint)
        layout.addWidget(self._joint_load)
        self._joint_label = QLabel(tr('rear_joint_layout.none'), body)
        self._joint_label.setWordWrap(True)
        self._joint_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._joint_label)
        joint_form = QFormLayout()
        self._joint_axis = QComboBox(body)
        for axis in AXES:
            self._joint_axis.addItem(axis.upper(), axis)
        self._joint_axis.setCurrentIndex(self._joint_axis.findData('y'))
        joint_form.addRow(tr('rear_joint_layout.axis'), self._joint_axis)
        layout.addLayout(joint_form)
        self._pair_mode.currentIndexChanged.connect(self._update_pair)
        self._pair_status = QLabel(body)
        self._pair_status.setWordWrap(True)
        layout.addWidget(self._pair_status)
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
        self._pair_plans = [ArmPlan(axes, tabs) for axes in ((0, 1), (0, 2), (1, 2))]
        for plan, label in zip(self._pair_plans, ('XY', 'XZ', 'YZ'), strict=True):
            tabs.addTab(plan, tr('rear_pair.tab', axes=label))
        self._pair_three_d = Weldment3D(tabs, is_current=self._pair_is_current, single_tube=True)
        tabs.addTab(self._pair_three_d, tr('rear_pair.tab_3d'))
        self._pair_assembly_3d = Weldment3D(tabs, is_current=self._pair_snapshot_is_current)
        tabs.addTab(self._pair_assembly_3d, tr('rear_pair.tab_both'))
        self._layout_3d = Weldment3D(tabs, is_current=self._layout_is_current, rear_joint_layout=True)
        tabs.addTab(self._layout_3d, tr('rear_joint_layout.tab_3d'))
        layout.addWidget(tabs, 1)
        self._save = QPushButton(tr('rear_tube.save'), body)
        self._save.clicked.connect(self._save_copy)
        layout.addWidget(self._save)
        self._save_pair = QPushButton(tr('rear_pair.save'), body)
        self._save_pair.clicked.connect(self._save_pair_copy)
        layout.addWidget(self._save_pair)
        self._save_layout = QPushButton(tr('rear_joint_layout.save'), body)
        self._save_layout.clicked.connect(self._save_layout_copy)
        layout.addWidget(self._save_layout)
        self._saved = QLabel(body)
        self._saved.setWordWrap(True)
        self._saved.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._saved)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, body)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._arm.currentIndexChanged.connect(self._refresh)
        self._radius.textChanged.connect(self._refresh)
        self._pair_mode.currentIndexChanged.connect(self._refresh_pair)
        self._pair_roll.textChanged.connect(self._refresh_pair)
        self._joint_axis.currentIndexChanged.connect(self._refresh_pair)
        self._wall.textChanged.connect(self._refresh)
        self._bend.toggled.connect(self._refresh)
        for field in self._fields:
            field.textChanged.connect(self._refresh)
        self._three_d.availabilityChanged.connect(self._update_save)
        self._pair_three_d.availabilityChanged.connect(self._update_save)
        self._pair_assembly_3d.availabilityChanged.connect(self._update_save)
        self._layout_3d.availabilityChanged.connect(self._update_save)
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._project_replaced)
        self._refresh()
        self._baseline = self._input_state()
        self._pair_baseline = self._pair_state()
        self._joint_baseline = self._joint_state()
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
        self._source_pair, self._saved_pair, self._pair_baseline = None, None, None
        self._saved_layout, self._joint_doc, self._joint_paths = None, None, ()
        self._joint_label.setText(tr('rear_joint_layout.none'))
        self._saved_candidate = None
        self._pending_project_changes = False
        widgets = [self._arm, self._radius, self._wall, self._bend, self._pair_mode, self._pair_roll,
                   self._joint_axis, *self._fields]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self._arm.setCurrentIndex(0)
            self._radius.setText('12')
            self._wall.setText('2')
            self._bend.setChecked(False)
            self._pair_mode.setCurrentIndex(0)
            self._pair_roll.setText('0')
            self._joint_axis.setCurrentIndex(self._joint_axis.findData('y'))
            for field in self._fields:
                field.clear()
        finally:
            for blocker in blockers:
                blocker.unblock()
        self._source_label.setText(tr('rear_tube.new'))
        self._baseline = self._input_state()
        self._pair_baseline = self._pair_state()
        self._joint_baseline = self._joint_state()
        self._refresh()

    def _open_file(self) -> None:
        revision, state, pair_state, joint_state = (self._revision, self._input_state(), self._pair_state(),
                                                     self._joint_state())
        selected, _ = QFileDialog.getOpenFileName(self, tr('rear_tube.open'), '', tr('arm_concept.assembly_filter'))
        if not selected:
            return
        if (revision != self._revision or state != self._input_state() or pair_state != self._pair_state() or
                joint_state != self._joint_state()):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.changed'))
            return
        try:
            path = Path(selected).absolute()
            resolved = path.resolve()
            document = read_document(path, 'assembly')
            layout_document = document if document['version'] == '0.10' else None
            if layout_document is not None:
                validate_rear_joint_layout(layout_document)
                pair_document = layout_document['pair']
            else:
                pair_document = document if document['version'] == '0.6' else None
            if pair_document is not None:
                document, _ = rear_pair_sides(pair_document)
            else:
                validate_rear_tube(document)
        except (KimFormatError, OSError, ValueError, RuntimeError):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('rear_tube.open_failed'))
            return
        if not self.confirm_close():
            return
        # Do not let changes made in a nested confirmation replace new work.
        if (revision != self._revision or state != self._input_state() or pair_state != self._pair_state() or
                joint_state != self._joint_state()):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.changed'))
            return
        self._source, self._source_paths, self._active = document, (path, resolved), False
        self._source_pair, self._saved_pair = pair_document, pair_document
        self._saved_layout = layout_document
        self._joint_doc = copy.deepcopy(layout_document['bushing']) if layout_document else None
        self._joint_paths = ()
        self._joint_label.setText(tr('rear_joint_layout.loaded', name=self._joint_doc['name'])
                                  if self._joint_doc else tr('rear_joint_layout.none'))
        self._pending_project_changes = False
        widgets = [self._arm, self._radius, self._wall, self._bend, self._pair_mode, self._pair_roll,
                   self._joint_axis, *self._fields]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self._arm.setCurrentIndex(self._arm.findData(document['arm']))
            self._radius.setText(str(document['radius_mm']))
            self._wall.setText(str(document['wall_mm']))
            self._pair_mode.setCurrentIndex(self._pair_mode.findData(pair_document['mode']) if pair_document else 0)
            self._pair_roll.setText(str(pair_document['roll_degrees']) if pair_document else '0')
            self._joint_axis.setCurrentIndex(self._joint_axis.findData(layout_document['axis'] if layout_document else 'y'))
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
        self._pair_baseline = self._pair_state()
        self._joint_baseline = self._joint_state()
        self._saved_candidate = document
        self._refresh()

    def _start_preview(self) -> None:
        if self._source is None:
            return
        self._active = True
        self._refresh()

    def _project_replaced(self) -> None:
        if self._source is not None:
            self._pending_project_changes = self._pending_project_changes or self._has_unsaved()
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

    def _joint_state(self) -> tuple[Any, ...]:
        return copy.deepcopy(self._joint_doc), self._joint_axis.currentData()

    def _load_joint(self) -> None:
        if not self._active:
            return
        revision, state, pair_state, joint_state = (self._revision, self._input_state(), self._pair_state(),
                                                     self._joint_state())
        selected, _ = QFileDialog.getOpenFileName(self, tr('rear_joint_layout.load'), '',
                                                   tr('arm_concept.assembly_filter'))
        if not selected:
            return
        def changed() -> bool:
            return (revision != self._revision or state != self._input_state() or
                    pair_state != self._pair_state() or joint_state != self._joint_state())
        if changed():
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.changed'))
            return
        try:
            path = Path(selected).absolute()
            resolved = path.resolve()
            doc = read_document(path, 'assembly')
            validate_joint_concept(doc)
            if doc['joint_type'] != 'bushing':
                raise KimFormatError('expected bushing')
        except (KimFormatError, OSError, ValueError, RuntimeError):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('rear_joint_layout.load_failed'))
            return
        if (self._joint_doc is not None and self._joint_baseline is not None and
                self._joint_doc != self._joint_baseline[0]):
            answer = QMessageBox.question(self, tr('weldment.discard_title'), tr('rear_joint_layout.replace'),
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        if changed():
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.changed'))
            return
        self._joint_doc, self._joint_paths = doc, (path, resolved)
        self._joint_label.setText(tr('rear_joint_layout.loaded', name=doc['name']))
        self._update_pair()
        self._refresh_pair()

    def _update_pair(self, *_args: object) -> None:
        mode = self._pair_mode.currentData()
        self._pair_roll.setEnabled(self._active and mode == 'same')
        self._pair_mode.setEnabled(self._active and self._arm.currentData() in PAIRS)
        self._joint_load.setEnabled(self._active)
        self._joint_axis.setEnabled(self._active and self._joint_doc is not None)
        self._pair.setEnabled(self._active and self._candidate is not None and
                              self._arm.currentData() in PAIRS and mode in ('same', 'mirror'))

    def _make_pair(self, candidate: dict[str, Any]) -> dict[str, Any]:
        mode = str(self._pair_mode.currentData())
        try:
            roll = float(self._pair_roll.text().strip().replace(',', '.')) if mode == 'same' else 0.0
        except ValueError as error:
            raise KimFormatError('invalid pair roll') from error
        return make_paired_rear_tube(candidate, mode, roll)

    def _make_pair_snapshot(self, candidate: dict[str, Any]) -> dict[str, Any]:
        mode = str(self._pair_mode.currentData())
        try:
            roll = float(self._pair_roll.text().strip().replace(',', '.')) if mode == 'same' else 0.0
        except ValueError as error:
            raise KimFormatError('invalid pair roll') from error
        return make_rear_pair_snapshot(candidate, mode, roll)

    def _pair_snapshot_is_current(self, snapshot: dict[str, Any]) -> bool:
        if self._candidate is None or not self._candidate_is_current(self._candidate):
            return False
        try:
            return self._make_pair_snapshot(self._candidate) == snapshot
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def _make_layout(self, candidate: dict[str, Any]) -> dict[str, Any]:
        if self._joint_doc is None:
            raise KimFormatError('bushing not selected')
        return make_rear_joint_layout(self._make_pair_snapshot(candidate), self._joint_doc,
                                      str(self._joint_axis.currentData()))

    def _layout_is_current(self, layout: dict[str, Any]) -> bool:
        if self._candidate is None or not self._candidate_is_current(self._candidate):
            return False
        try:
            return self._make_layout(self._candidate) == layout
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def _pair_is_current(self, paired: dict[str, Any]) -> bool:
        if self._candidate is None or not self._candidate_is_current(self._candidate):
            return False
        try:
            return self._make_pair(self._candidate) == paired
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def _refresh_pair(self, *_args: object) -> None:
        for plan in self._pair_plans:
            plan.set_view(None)
        self._pair_three_d.set_document(None)
        self._pair_assembly_3d.set_document(None)
        self._layout_3d.set_document(None)
        self._update_save()
        self._update_edit_status()
        candidate = self._candidate
        mode = self._pair_mode.currentData()
        if (candidate is None or candidate['arm'] not in PAIRS or mode not in ('same', 'mirror') or
                not self._candidate_is_current(candidate)):
            self._pair_status.setText(tr('rear_pair.preview_off'))
            return
        try:
            paired = self._make_pair(candidate)
            snapshot = self._make_pair_snapshot(candidate)
            path = rear_tube_centerline(paired)
            view = make_niva_arm_view(Project.from_dict(paired['scheme']), paired['arm'])
        except (KimFormatError, ValueError, TypeError, OverflowError):
            self._pair_status.setText(tr('rear_pair.preview_invalid'))
            return
        for plan in self._pair_plans:
            plan.set_view(view, path)
        self._pair_three_d.set_document(paired)
        self._pair_assembly_3d.set_document(snapshot)
        if self._joint_doc is not None:
            try:
                self._layout_3d.set_document(self._make_layout(candidate))
            except (KimFormatError, ValueError, TypeError, OverflowError):
                self._layout_3d.set_document(None)
        self._pair_status.setText(tr('rear_pair.preview_ready'))
        self._update_save()

    def _apply_pair(self) -> None:
        candidate = self._candidate
        if candidate is None or not self._active or not self._candidate_is_current(candidate):
            self._refresh()
            return
        try:
            paired = self._make_pair(candidate)
        except (KimFormatError, ValueError, TypeError, OverflowError):
            QMessageBox.warning(self, tr('rear_pair.title'), tr('rear_pair.failed'))
            return
        widgets = [self._arm, self._bend, *self._fields]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self._arm.setCurrentIndex(self._arm.findData(paired['arm']))
            bend = paired['bend']
            self._bend.setChecked(bend is not None)
            if bend is not None:
                for field, value in zip(self._fields, [*bend['vertex_mm'], bend['radius_mm']], strict=True):
                    field.setText(str(value))
        finally:
            for blocker in blockers:
                blocker.unblock()
        self._refresh()

    def _refresh(self, *_args: object) -> None:
        self._revision += 1
        self._saved.clear()
        self._candidate = None
        self._refresh_pair()
        self._update_pair()
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
        self._update_pair()
        self._refresh_pair()
        for plan in self._plans:
            plan.set_view(view, path)
        self._three_d.set_document(candidate)
        if self._source is not None and not self._active:
            key = ('rear_pair.snapshot_modified' if self._pair_state() != self._pair_baseline or
                   self._joint_state() != self._joint_baseline else 'rear_tube.snapshot')
            self._status.setText(tr(key))
        elif self._source is not None:
            matches = (self._source['arm'] == candidate['arm'] and
                       rear_tube_points(self._source) == rear_tube_points(candidate))
            if matches and self._source_pair is not None:
                try:
                    other = PAIRS[self._source['arm']]
                    old_view = make_niva_arm_view(Project.from_dict(self._source['scheme']), other)
                    new_view = make_niva_arm_view(Project.from_dict(candidate['scheme']), other)
                    matches = old_view.points == new_view.points
                except (KeyError, ValueError, TypeError, OverflowError):
                    matches = False
                self._status.setText(tr('rear_pair.match' if matches else 'rear_tube.different'))
            else:
                self._status.setText(tr('rear_tube.match' if matches else 'rear_tube.different'))
        else:
            self._status.setText(tr('rear_tube.ready'))
        self._update_save()
        self._update_edit_status()

    def _input_state(self) -> tuple[Any, ...]:
        return (self._arm.currentData(), self._radius.text(), self._wall.text(), self._bend.isChecked(),
                tuple(field.text() for field in self._fields) if self._bend.isChecked() else ())

    def _pair_state(self) -> tuple[Any, ...]:
        mode = self._pair_mode.currentData()
        return (mode, self._pair_roll.text() if mode == 'same' else '')

    def _has_unsaved(self) -> bool:
        pair_changed = (self._pair_state() != self._pair_baseline or
                        (self._saved_pair is not None and self._active and
                         self._candidate != self._saved_pair['source']))
        layout_changed = False
        if self._active and self._saved_layout is not None:
            try:
                layout_changed = self._candidate is None or self._make_layout(self._candidate) != self._saved_layout
            except (KimFormatError, ValueError, TypeError, OverflowError):
                layout_changed = True
        return (self._baseline is not None and (self._input_state() != self._baseline or
                self._joint_state() != self._joint_baseline or layout_changed or
                self._pending_project_changes or pair_changed or
                (self._active and self._saved_candidate is not None and self._saved_candidate != self._candidate)))

    def _update_edit_status(self) -> None:
        self._edit_status.setText(tr("rear_tube.unsaved") if self._has_unsaved() else "")

    def confirm_close(self) -> bool:
        if self._closing_confirmed or not self._has_unsaved():
            return True
        state, pair_state, joint_state, revision = self._input_state(), self._pair_state(), self._joint_state(), self._revision
        answer = QMessageBox.question(self, tr("weldment.discard_title"), tr("rear_tube.discard"),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return (answer == QMessageBox.StandardButton.Yes and state == self._input_state() and
                pair_state == self._pair_state() and joint_state == self._joint_state() and revision == self._revision)

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
        paired = self._pair_three_d._document
        self._save_pair.setEnabled(self._active and paired is not None and self._pair_is_current(paired) and
                                   self._three_d.can_save() and self._pair_three_d.can_save() and
                                   self._pair_assembly_3d.can_save())
        layout = self._layout_3d._document
        self._save_layout.setEnabled(self._active and layout is not None and self._layout_is_current(layout) and
                                     self._three_d.can_save() and self._pair_three_d.can_save() and
                                     self._pair_assembly_3d.can_save() and self._layout_3d.can_save())

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
            if any(same_project_file(path, source) for source in (*self._source_paths, *self._joint_paths)):
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

    def _save_pair_copy(self) -> None:
        candidate = self._candidate
        paired = self._pair_three_d._document
        if (not self._active or candidate is None or paired is None or not self._pair_is_current(paired) or
                not self._three_d.can_save() or not self._pair_three_d.can_save() or
                not self._pair_assembly_3d.can_save()):
            return
        try:
            snapshot = self._make_pair_snapshot(candidate)
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return
        revision, state, pair_state = self._revision, self._input_state(), self._pair_state()
        gens = (self._three_d.generation, self._pair_three_d.generation, self._pair_assembly_3d.generation)
        selected, _ = QFileDialog.getSaveFileName(self, tr('rear_pair.save'), '', tr('arm_concept.assembly_filter'))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kima':
            path = path.with_name(path.name + '.kima')
        if (revision != self._revision or state != self._input_state() or pair_state != self._pair_state() or
                gens != (self._three_d.generation, self._pair_three_d.generation, self._pair_assembly_3d.generation) or
                not self._three_d.can_save() or not self._pair_three_d.can_save() or
                not self._pair_assembly_3d.can_save() or
                not self._pair_is_current(paired)):
            QMessageBox.warning(self, tr('rear_pair.title'), tr('weldment.changed'))
            return
        try:
            if any(same_project_file(path, source) for source in (*self._source_paths, *self._joint_paths)):
                raise KimFormatError('original source path')
            if self.controller.is_protected_export_target(path):
                raise KimFormatError('protected project')
            write_document(path, 'assembly', snapshot, overwrite=False)
        except (KimFormatError, OSError, ValueError, TypeError, RuntimeError):
            QMessageBox.warning(self, tr('rear_pair.title'), tr('weldment.save_failed'))
            self._refresh()
            return
        self._baseline = self._input_state()
        self._pair_baseline = self._pair_state()
        self._saved_candidate = candidate
        self._saved_pair = snapshot
        self._pending_project_changes = False
        self._update_edit_status()
        self._saved.setText(tr('weldment.saved', path=str(path)))

    def _save_layout_copy(self) -> None:
        layout = self._layout_3d._document
        panels = (self._three_d, self._pair_three_d, self._pair_assembly_3d, self._layout_3d)
        if (not self._active or layout is None or not self._layout_is_current(layout) or
                not all(panel.can_save() for panel in panels)):
            return
        revision, state, pair_state, joint_state = (self._revision, self._input_state(), self._pair_state(),
                                                     self._joint_state())
        generations = tuple(panel.generation for panel in panels)
        selected, _ = QFileDialog.getSaveFileName(self, tr('rear_joint_layout.save'), '',
                                                   tr('arm_concept.assembly_filter'))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kima':
            path = path.with_name(path.name + '.kima')
        if (revision != self._revision or state != self._input_state() or pair_state != self._pair_state() or
                joint_state != self._joint_state() or generations != tuple(panel.generation for panel in panels) or
                not all(panel.can_save() for panel in panels) or not self._layout_is_current(layout)):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.changed'))
            return
        try:
            if any(same_project_file(path, source) for source in (*self._source_paths, *self._joint_paths)):
                raise KimFormatError('original source path')
            if self.controller.is_protected_export_target(path):
                raise KimFormatError('protected project')
            write_document(path, 'assembly', layout, overwrite=False)
        except (KimFormatError, OSError, ValueError, TypeError, RuntimeError):
            QMessageBox.warning(self, tr('rear_tube.title'), tr('weldment.save_failed'))
            self._refresh()
            return
        self._baseline = self._input_state()
        self._pair_baseline = self._pair_state()
        self._joint_baseline = self._joint_state()
        self._saved_candidate = self._candidate
        self._saved_pair = layout['pair']
        self._saved_layout = layout
        self._pending_project_changes = False
        self._update_edit_status()
        self._saved.setText(tr('weldment.saved', path=str(path)))

    def shutdown(self) -> bool:
        first = self._three_d.shutdown()
        second = self._pair_three_d.shutdown()
        both = self._pair_assembly_3d.shutdown()
        layout = self._layout_3d.shutdown()
        return first and second and both and layout

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
