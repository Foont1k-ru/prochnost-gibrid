"""Передний трубчатый рычаг: две незавершённые трубы по текущей схеме."""
from __future__ import annotations

import copy
import math
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
from ..model.front_joint_layout import make_front_joint_layout, validate_front_joint_layout
from ..model.front_pair_snapshot import front_pair_sides, make_front_pair_snapshot, mirror_front_tube_arm
from ..model.front_same_pair import front_same_pair_sides, make_front_same_pair
from ..model.front_tube_arm import (
    front_tube_arm_centerlines,
    front_tube_arm_points,
    make_front_tube_arm,
    validate_front_tube_arm,
)
from ..model.joint_concept import validate_joint_concept
from ..model.kim_format import KimFormatError, read_document, write_document
from ..model.niva_arm_views import FRONT, make_niva_arm_view
from .bend_editor import BendEditor
from .controller import AppController
from .niva_arms_dialog import ArmPlan
from .weldment_3d import Weldment3D


class FrontTubesDialog(QDialog):
    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._candidate: dict[str, Any] | None = None
        self._source: dict[str, Any] | None = None
        self._saved_pair: dict[str, Any] | None = None
        self._saved_layout: dict[str, Any] | None = None
        self._joint_docs: dict[str, dict[str, Any] | None] = {'ball': None, 'bushing': None}
        self._joint_paths: dict[str, tuple[Path, ...]] = {'ball': (), 'bushing': ()}
        self._joint_baseline = self._joint_state()
        self._source_paths: tuple[Path, ...] = ()
        self._active = True
        self._pending_project_changes = False
        self._revision = 0
        self._closing_confirmed = False
        self._saved_candidate: dict[str, Any] | None = None
        self._baseline: tuple[Any, ...] | None = None
        self._pair_baseline: str | None = None
        self.setWindowTitle(tr('front_tubes.title'))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(800, 790)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget(scroll)
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        warning = QLabel(tr('front_tubes.warning'), body)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self._new = QPushButton(tr('front_tubes.new_button'), body)
        self._new.clicked.connect(self._new_draft)
        layout.addWidget(self._new)
        self._open = QPushButton(tr('front_tubes.open'), body)
        self._open.clicked.connect(self._open_file)
        layout.addWidget(self._open)
        self._source_label = QLabel(tr('front_tubes.new'), body)
        self._source_label.setWordWrap(True)
        self._source_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._source_label)
        self._activate = QPushButton(tr('front_tubes.activate'), body)
        self._activate.clicked.connect(self._start_preview)
        self._activate.setVisible(False)
        layout.addWidget(self._activate)
        form = QFormLayout()
        self._arm = QComboBox(body)
        for key in FRONT:
            self._arm.addItem(tr(f'niva_arms.{key}'), key)
        form.addRow(tr('niva_arms.choose'), self._arm)
        self._radius = self._number_field(body, '12', tr('front_tubes.radius'))
        self._wall = self._number_field(body, '2', tr('front_tubes.wall'))
        form.addRow(tr('front_tubes.radius'), self._radius)
        form.addRow(tr('front_tubes.wall'), self._wall)
        layout.addLayout(form)
        self._bend_editor = BendEditor(body)
        layout.addWidget(self._bend_editor)
        self._auto_mirror = QCheckBox(tr('front_pair.auto'), body)
        self._auto_mirror.setChecked(True)
        layout.addWidget(self._auto_mirror)
        self._last_arm = str(self._arm.currentData())
        self._mirror = QPushButton(tr('front_pair.apply'), body)
        self._mirror.clicked.connect(self._apply_mirror)
        layout.addWidget(self._mirror)
        mode_form = QFormLayout()
        self._pair_mode = QComboBox(body)
        self._pair_mode.addItem(tr('front_same.mirror'), 'mirror')
        self._pair_mode.addItem(tr('front_same.same'), 'same')
        mode_form.addRow(tr('front_same.mode'), self._pair_mode)
        layout.addLayout(mode_form)
        pair_note = QLabel(tr('front_same.note'), body)
        pair_note.setWordWrap(True)
        layout.addWidget(pair_note)
        mirror_note = QLabel(tr('front_pair.preview'), body)
        mirror_note.setWordWrap(True)
        layout.addWidget(mirror_note)
        joint_note = QLabel(tr('front_joint_layout.note'), body)
        joint_note.setWordWrap(True)
        layout.addWidget(joint_note)
        self._joint_labels: dict[str, QLabel] = {}
        self._joint_buttons: dict[str, QPushButton] = {}
        for kind in ('ball', 'bushing'):
            button = QPushButton(tr(f'front_joint_layout.load_{kind}'), body)
            button.clicked.connect(lambda _checked=False, k=kind: self._load_joint(k))
            self._joint_buttons[kind] = button
            layout.addWidget(button)
            joint_label = QLabel(tr('front_joint_layout.none'), body)
            joint_label.setWordWrap(True)
            joint_label.setTextFormat(Qt.TextFormat.PlainText)
            self._joint_labels[kind] = joint_label
            layout.addWidget(joint_label)
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
        self._three_d = Weldment3D(tabs, is_current=self._candidate_is_current)
        tabs.addTab(self._three_d, tr('front_tubes.tab_3d'))
        self._mirror_plans = [ArmPlan(axes, tabs) for axes in ((0, 1), (0, 2), (1, 2))]
        for plan, label in zip(self._mirror_plans, ('XY', 'XZ', 'YZ'), strict=True):
            tabs.addTab(plan, tr('front_pair.tab', axes=label))
        self._pair_3d = Weldment3D(tabs, is_current=self._pair_is_current, four_tubes=True)
        tabs.addTab(self._pair_3d, tr('front_pair.tab_both'))
        self._layout_3d = Weldment3D(tabs, is_current=self._layout_is_current, joint_layout=True)
        tabs.addTab(self._layout_3d, tr('front_joint_layout.tab_3d'))
        layout.addWidget(tabs, 1)
        self._save = QPushButton(tr('front_tubes.save'), body)
        self._save.clicked.connect(self._save_copy)
        layout.addWidget(self._save)
        self._save_pair = QPushButton(tr('front_pair.save'), body)
        self._save_pair.clicked.connect(self._save_pair_copy)
        layout.addWidget(self._save_pair)
        self._save_layout = QPushButton(tr('front_joint_layout.save'), body)
        self._save_layout.clicked.connect(self._save_layout_copy)
        layout.addWidget(self._save_layout)
        self._saved = QLabel(body)
        self._saved.setWordWrap(True)
        self._saved.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._saved)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, body)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._arm.currentIndexChanged.connect(self._arm_changed)
        self._radius.textChanged.connect(self._refresh)
        self._wall.textChanged.connect(self._refresh)
        self._pair_mode.currentIndexChanged.connect(self._refresh)
        self._bend_editor.changed.connect(self._refresh)
        self._three_d.availabilityChanged.connect(self._update_save)
        self._pair_3d.availabilityChanged.connect(self._update_save)
        self._layout_3d.availabilityChanged.connect(self._update_save)
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._project_replaced)
        self._refresh()
        self._baseline = self._input_state()
        self._pair_baseline = str(self._pair_mode.currentData())
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
        self._saved_pair, self._saved_layout = None, None
        self._joint_docs = {'ball': None, 'bushing': None}
        self._joint_paths = {'ball': (), 'bushing': ()}
        self._joint_baseline = self._joint_state()
        self._update_joint_labels()
        self._pending_project_changes = False
        widgets = [self._arm, self._radius, self._wall, self._pair_mode]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self._arm.setCurrentIndex(0)
            self._pair_mode.setCurrentIndex(self._pair_mode.findData('mirror'))
            self._radius.setText('12')
            self._wall.setText('2')
            self._bend_editor.load({})
        finally:
            for blocker in blockers:
                blocker.unblock()
        self._source_label.setText(tr('front_tubes.new'))
        self._baseline = self._input_state()
        self._pair_baseline = str(self._pair_mode.currentData())
        self._refresh()

    def _open_file(self) -> None:
        revision, state, joint_state = self._revision, self._input_state(), self._joint_state()
        selected, _ = QFileDialog.getOpenFileName(self, tr('front_tubes.open'), '', tr('arm_concept.assembly_filter'))
        if not selected:
            return
        if revision != self._revision or state != self._input_state() or joint_state != self._joint_state():
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.changed'))
            return
        try:
            path = Path(selected).absolute()
            resolved = path.resolve()
            document = read_document(path, 'assembly')
            layout_document = document if document['version'] in ('0.9', '0.12') else None
            if layout_document is not None:
                validate_front_joint_layout(layout_document)
                pair_document = layout_document['pair']
            else:
                pair_document = document if document['version'] in ('0.7', '0.11') else None
            if pair_document is not None:
                document, _ = (front_same_pair_sides(pair_document) if pair_document['version'] == '0.11'
                               else front_pair_sides(pair_document))
            else:
                validate_front_tube_arm(document)
        except (KimFormatError, OSError, ValueError, RuntimeError):
            QMessageBox.warning(self, tr('front_tubes.title'), tr('front_tubes.open_failed'))
            return
        if not self.confirm_close():
            return
        # Do not let changes made in a nested confirmation replace new work.
        if revision != self._revision or state != self._input_state() or joint_state != self._joint_state():
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.changed'))
            return
        self._source, self._source_paths, self._active = document, (path, resolved), False
        self._saved_pair = pair_document
        self._saved_layout = layout_document
        self._joint_docs = {k: copy.deepcopy(layout_document[k]) if layout_document else None
                            for k in ('ball', 'bushing')}
        self._joint_paths = {'ball': (), 'bushing': ()}
        self._joint_baseline = self._joint_state()
        self._update_joint_labels()
        self._pending_project_changes = False
        widgets = [self._arm, self._radius, self._wall, self._pair_mode]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self._arm.setCurrentIndex(self._arm.findData(document['arm']))
            self._pair_mode.setCurrentIndex(self._pair_mode.findData(
                'same' if pair_document and pair_document['version'] == '0.11' else 'mirror'))
            self._radius.setText(str(document['radius_mm']))
            self._wall.setText(str(document['wall_mm']))
            self._bend_editor.load(document['bends'])
        finally:
            for blocker in blockers:
                blocker.unblock()
        self._source_label.setText(tr('front_tubes.source', path=str(path), name=document['name']))
        self._baseline = self._input_state()
        self._pair_baseline = str(self._pair_mode.currentData())
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
        try:
            radius = float(self._radius.text().strip().replace(',', '.'))
            wall = float(self._wall.text().strip().replace(',', '.'))
        except ValueError as error:
            raise KimFormatError('tube dimensions are required') from error
        result = make_front_tube_arm(self.controller.project, str(self._arm.currentData()), radius, wall,
                                     self._bend_editor.values())
        if self._source is not None:
            result['name'] = self._source['name']
        return result

    def _joint_state(self) -> dict[str, dict[str, Any] | None]:
        return copy.deepcopy(self._joint_docs)

    def _update_joint_labels(self) -> None:
        for kind, label in self._joint_labels.items():
            doc = self._joint_docs[kind]
            label.setText(tr('front_joint_layout.loaded', name=doc['name']) if doc else tr('front_joint_layout.none'))

    def _load_joint(self, kind: str) -> None:
        if not self._active:
            return
        revision, state, joint_state = self._revision, self._input_state(), self._joint_state()
        selected, _ = QFileDialog.getOpenFileName(self, tr(f'front_joint_layout.load_{kind}'), '',
                                                   tr('arm_concept.assembly_filter'))
        if not selected:
            return
        if revision != self._revision or state != self._input_state() or joint_state != self._joint_state():
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.changed'))
            return
        try:
            path = Path(selected).absolute()
            resolved = path.resolve()
            doc = read_document(path, 'assembly')
            validate_joint_concept(doc)
            if doc['joint_type'] != kind:
                raise KimFormatError('wrong joint type')
        except (KimFormatError, OSError, ValueError, RuntimeError):
            QMessageBox.warning(self, tr('front_tubes.title'), tr('front_joint_layout.load_failed'))
            return
        if self._joint_docs[kind] is not None and self._joint_docs[kind] != self._joint_baseline[kind]:
            answer = QMessageBox.question(self, tr('weldment.discard_title'), tr('front_joint_layout.replace'),
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        if revision != self._revision or state != self._input_state() or joint_state != self._joint_state():
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.changed'))
            return
        self._joint_docs[kind] = doc
        self._joint_paths[kind] = (path, resolved)
        self._update_joint_labels()
        self._refresh()

    def _arm_changed(self, *_args: object) -> None:
        old, new = self._last_arm, str(self._arm.currentData())
        opposite = old.removesuffix('_left') + '_right' if old.endswith('_left') else old.removesuffix('_right') + '_left'
        if self._auto_mirror.isChecked() and new == opposite:
            changes: list[tuple[QLineEdit, str]] = []
            try:
                for leg, check in self._bend_editor.checks.items():
                    if check.isChecked():
                        field = self._bend_editor.fields[leg][1]
                        text = field.text().strip()
                        number = float(text.replace(',', '.'))
                        if not math.isfinite(number):
                            raise ValueError('nonfinite')
                        reflected = text[1:] if text.startswith('-') else '-' + text.lstrip('+')
                        if len(reflected) > field.maxLength():
                            raise ValueError('too long')
                        changes.append((field, reflected))
            except ValueError:
                with QSignalBlocker(self._arm):
                    self._arm.setCurrentIndex(self._arm.findData(old))
                QMessageBox.warning(self, tr('front_tubes.title'), tr('front_pair.auto_failed'))
                return
            for field, text in changes:
                with QSignalBlocker(field):
                    field.setText(text)
        self._last_arm = new
        self._refresh()

    def _apply_mirror(self) -> None:
        candidate = self._candidate
        if not self._active or candidate is None or not self._candidate_is_current(candidate):
            self._refresh()
            return
        try:
            paired = mirror_front_tube_arm(candidate)
        except (KimFormatError, ValueError, TypeError, OverflowError):
            QMessageBox.warning(self, tr('front_tubes.title'), tr('front_pair.failed'))
            return
        with QSignalBlocker(self._arm):
            self._arm.setCurrentIndex(self._arm.findData(paired['arm']))
        self._bend_editor.load(paired['bends'])
        self._refresh()

    def _refresh(self, *_args: object) -> None:
        self._last_arm = str(self._arm.currentData())
        self._revision += 1
        self._saved.clear()
        self._candidate = None
        self._mirror.setEnabled(False)
        for widget in (self._arm, self._radius, self._wall, self._pair_mode, *self._joint_buttons.values()):
            widget.setEnabled(self._active)
        self._bend_editor.set_editable(self._active)
        self._activate.setVisible(self._source is not None)
        self._activate.setEnabled(self._source is not None and not self._active)
        for plan in (*self._plans, *self._mirror_plans):
            plan.set_view(None)
        self._three_d.set_document(None)
        self._pair_3d.set_document(None)
        self._layout_3d.set_document(None)
        self._update_save()
        try:
            candidate = self._source if self._source is not None and not self._active else self._make_candidate()
            paths = front_tube_arm_centerlines(candidate)
            view = make_niva_arm_view(Project.from_dict(candidate['scheme']), candidate['arm'])
        except (KimFormatError, ValueError, TypeError, OverflowError):
            self._status.setText(tr('front_tubes.invalid'))
            self._update_edit_status()
            return
        self._candidate = candidate
        self._mirror.setEnabled(self._active)
        for plan in self._plans:
            plan.set_view(view, paths=paths)
        self._three_d.set_document(candidate)
        try:
            snapshot = self._make_pair(candidate)
            _, paired = (front_same_pair_sides(snapshot) if snapshot['version'] == '0.11'
                         else front_pair_sides(snapshot))
            mirror_paths = front_tube_arm_centerlines(paired)
            mirror_view = make_niva_arm_view(Project.from_dict(paired['scheme']), paired['arm'])
        except (KimFormatError, ValueError, TypeError, OverflowError):
            self._status.setText(tr('front_same.invalid'))
            self._update_save()
            self._update_edit_status()
            return
        for plan in self._mirror_plans:
            plan.set_view(mirror_view, paths=mirror_paths)
        self._pair_3d.set_document(snapshot)
        if self._joint_docs['ball'] is not None and self._joint_docs['bushing'] is not None:
            try:
                layout_doc = make_front_joint_layout(snapshot, self._joint_docs['ball'], self._joint_docs['bushing'])
                self._layout_3d.set_document(layout_doc)
            except (KimFormatError, ValueError, TypeError, OverflowError):
                self._layout_3d.set_document(None)
        if self._source is not None and not self._active:
            key = 'front_joint_layout.snapshot_modified' if self._joint_state() != self._joint_baseline else 'front_tubes.snapshot'
            self._status.setText(tr(key))
        elif self._source is not None:
            matches = (self._source['arm'] == candidate['arm'] and
                       front_tube_arm_points(self._source) == front_tube_arm_points(candidate))
            self._status.setText(tr('front_tubes.match' if matches else 'front_tubes.different'))
        else:
            self._status.setText(tr('front_tubes.ready'))
        self._update_save()
        self._update_edit_status()

    def _input_state(self) -> tuple[Any, ...]:
        return (self._arm.currentData(), self._radius.text(), self._wall.text(), self._bend_editor.state(),
                self._pair_mode.currentData())

    def _has_unsaved(self) -> bool:
        pair_changed = str(self._pair_mode.currentData()) != self._pair_baseline
        if self._active and (self._saved_pair is not None or self._saved_layout is not None):
            try:
                pair = self._make_pair(self._candidate) if self._candidate is not None else None
                pair_changed = (pair_changed or (self._saved_pair is not None and pair != self._saved_pair) or
                                (self._saved_layout is not None and pair != self._saved_layout['pair']))
            except (KimFormatError, ValueError, TypeError, OverflowError):
                pair_changed = True
        return (self._baseline is not None and (self._input_state() != self._baseline or pair_changed or
                self._joint_state() != self._joint_baseline or self._pending_project_changes or
                (self._active and self._saved_candidate is not None and self._saved_candidate != self._candidate)))

    def _update_edit_status(self) -> None:
        self._edit_status.setText(tr("front_tubes.unsaved") if self._has_unsaved() else "")

    def confirm_close(self) -> bool:
        if self._closing_confirmed or not self._has_unsaved():
            return True
        state, joint_state, revision = self._input_state(), self._joint_state(), self._revision
        answer = QMessageBox.question(self, tr("weldment.discard_title"), tr("front_tubes.discard"),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return (answer == QMessageBox.StandardButton.Yes and state == self._input_state() and
                joint_state == self._joint_state() and revision == self._revision)

    def _candidate_is_current(self, candidate: dict[str, Any]) -> bool:
        if candidate != self._candidate:
            return False
        if self._source is not None and not self._active:
            return candidate == self._source
        try:
            return self._make_candidate() == candidate
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def _make_pair(self, candidate: dict[str, Any]) -> dict[str, Any]:
        if self._pair_mode.currentData() == 'same':
            return make_front_same_pair(candidate)
        if self._pair_mode.currentData() == 'mirror':
            return make_front_pair_snapshot(candidate)
        raise KimFormatError('unknown pair mode')

    def _pair_is_current(self, snapshot: dict[str, Any]) -> bool:
        if self._candidate is None or not self._candidate_is_current(self._candidate):
            return False
        try:
            return self._make_pair(self._candidate) == snapshot
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def _layout_is_current(self, layout: dict[str, Any]) -> bool:
        if self._candidate is None or not self._candidate_is_current(self._candidate):
            return False
        ball, bushing = self._joint_docs['ball'], self._joint_docs['bushing']
        if ball is None or bushing is None:
            return False
        try:
            return make_front_joint_layout(self._make_pair(self._candidate), ball, bushing) == layout
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def _update_save(self, *_args: object) -> None:
        self._save.setEnabled(self._active and self._candidate is not None and self._three_d.can_save())
        pair = self._pair_3d._document
        self._save_pair.setEnabled(self._active and pair is not None and self._pair_is_current(pair) and
                                   self._three_d.can_save() and self._pair_3d.can_save())
        layout = self._layout_3d._document
        self._save_layout.setEnabled(self._active and layout is not None and self._layout_is_current(layout) and
                                     self._three_d.can_save() and self._pair_3d.can_save() and
                                     self._layout_3d.can_save())

    def _save_copy(self) -> None:
        candidate = self._candidate
        if not self._active or candidate is None or not self._three_d.can_save():
            return
        revision, generation = self._revision, self._three_d.generation
        selected, _ = QFileDialog.getSaveFileName(self, tr('front_tubes.save'), '', tr('arm_concept.assembly_filter'))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kima':
            path = path.with_name(path.name + '.kima')
        if (revision != self._revision or generation != self._three_d.generation or not self._three_d.can_save()):
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.changed'))
            return
        try:
            if not self._candidate_is_current(candidate):
                raise KimFormatError('inputs changed')
            protected_sources = (*self._source_paths, *self._joint_paths['ball'], *self._joint_paths['bushing'])
            if any(same_project_file(path, source) for source in protected_sources):
                raise KimFormatError('original source path')
            if self.controller.is_protected_export_target(path):
                raise KimFormatError('protected project')
            write_document(path, 'assembly', candidate, overwrite=False)
        except (KimFormatError, OSError, ValueError, TypeError, RuntimeError):
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.save_failed'))
            self._refresh()
            return
        self._baseline = self._input_state()
        self._saved_candidate = candidate
        self._pending_project_changes = False
        self._update_edit_status()
        self._saved.setText(tr('weldment.saved', path=str(path)))

    def _save_pair_copy(self) -> None:
        pair = self._pair_3d._document
        if (not self._active or pair is None or not self._pair_is_current(pair) or
                not self._three_d.can_save() or not self._pair_3d.can_save()):
            return
        revision, state = self._revision, self._input_state()
        gens = (self._three_d.generation, self._pair_3d.generation)
        selected, _ = QFileDialog.getSaveFileName(self, tr('front_pair.save'), '', tr('arm_concept.assembly_filter'))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kima':
            path = path.with_name(path.name + '.kima')
        if (revision != self._revision or state != self._input_state() or
                gens != (self._three_d.generation, self._pair_3d.generation) or
                not self._three_d.can_save() or not self._pair_3d.can_save() or not self._pair_is_current(pair)):
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.changed'))
            return
        try:
            protected_sources = (*self._source_paths, *self._joint_paths['ball'], *self._joint_paths['bushing'])
            if any(same_project_file(path, source) for source in protected_sources):
                raise KimFormatError('original source path')
            if self.controller.is_protected_export_target(path):
                raise KimFormatError('protected project')
            write_document(path, 'assembly', pair, overwrite=False)
        except (KimFormatError, OSError, ValueError, TypeError, RuntimeError):
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.save_failed'))
            self._refresh()
            return
        self._baseline = self._input_state()
        self._saved_candidate = self._candidate
        self._saved_pair = pair
        self._pair_baseline = str(self._pair_mode.currentData())
        self._pending_project_changes = False
        self._update_edit_status()
        self._saved.setText(tr('weldment.saved', path=str(path)))

    def _save_layout_copy(self) -> None:
        layout = self._layout_3d._document
        if (not self._active or layout is None or not self._layout_is_current(layout) or
                not self._three_d.can_save() or not self._pair_3d.can_save() or not self._layout_3d.can_save()):
            return
        revision, state, joints = self._revision, self._input_state(), self._joint_state()
        gens = (self._three_d.generation, self._pair_3d.generation, self._layout_3d.generation)
        selected, _ = QFileDialog.getSaveFileName(self, tr('front_joint_layout.save'), '',
                                                   tr('arm_concept.assembly_filter'))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kima':
            path = path.with_name(path.name + '.kima')
        if (revision != self._revision or state != self._input_state() or joints != self._joint_state() or
                gens != (self._three_d.generation, self._pair_3d.generation, self._layout_3d.generation) or
                not self._three_d.can_save() or not self._pair_3d.can_save() or not self._layout_3d.can_save() or
                not self._layout_is_current(layout)):
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.changed'))
            return
        try:
            sources = (*self._source_paths, *self._joint_paths['ball'], *self._joint_paths['bushing'])
            if any(same_project_file(path, source) for source in sources):
                raise KimFormatError('original source path')
            if self.controller.is_protected_export_target(path):
                raise KimFormatError('protected project')
            write_document(path, 'assembly', layout, overwrite=False)
        except (KimFormatError, OSError, ValueError, TypeError, RuntimeError):
            QMessageBox.warning(self, tr('front_tubes.title'), tr('weldment.save_failed'))
            self._refresh()
            return
        self._baseline = self._input_state()
        self._saved_candidate = self._candidate
        self._saved_pair = layout['pair']
        self._pair_baseline = str(self._pair_mode.currentData())
        self._saved_layout = layout
        self._joint_baseline = self._joint_state()
        self._pending_project_changes = False
        self._update_edit_status()
        self._saved.setText(tr('weldment.saved', path=str(path)))

    def shutdown(self) -> bool:
        single = self._three_d.shutdown()
        pair = self._pair_3d.shutdown()
        layout = self._layout_3d.shutdown()
        return single and pair and layout

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
