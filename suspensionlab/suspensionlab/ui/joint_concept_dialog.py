"""Отдельный условный узел: пользовательские параметры, разрез и частичный CAD."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, QSignalBlocker, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
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
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..model.autosave_guard import same_project_file
from ..model.joint_concept import DEFAULTS, make_joint_concept, validate_joint_concept
from ..model.kim_format import KimFormatError, read_document, write_document
from .controller import AppController
from .weldment_3d import Weldment3D


class JointSection(QWidget):
    """Осевой схематичный разрез без расчёта, не чертёж для изготовления."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document: dict[str, Any] | None = None
        self.setMinimumSize(320, 260)

    def set_document(self, document: dict[str, Any] | None) -> None:
        self.document = document
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        if self.document is None:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), tr('joint_concept.invalid'))
            return
        p = self.document['parameters']
        radius = float(p['outer_radius_mm'])
        if self.document['joint_type'] == 'ball':
            bottom, top = -radius, float(p['pin_length_mm'])
        else:
            bottom, top = -float(p['pin_length_mm'])/2, float(p['pin_length_mm'])/2
        scale = min(max(self.width()-80, 1)/(radius*2), max(self.height()-80, 1)/(top-bottom))
        middle = (top+bottom)/2
        def rect(x1: float, z1: float, x2: float, z2: float) -> QRectF:
            return QRectF(self.width()/2+x1*scale, self.height()/2-(z2-middle)*scale,
                          (x2-x1)*scale, (z2-z1)*scale)
        painter.setPen(QPen(QColor('#387fa3'), 1.5))
        painter.setBrush(QColor('#9cc5d6'))
        if self.document['joint_type'] == 'ball':
            painter.drawEllipse(rect(-radius, -radius, radius, radius))
            cavity = float(p['cavity_radius_mm'])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.palette().base())
            painter.drawEllipse(rect(-cavity, -cavity, cavity, cavity))
            opening = float(p['opening_radius_mm'])
            painter.drawRect(rect(-opening, 0, opening, radius + 1))
            head = float(p['ball_radius_mm'])
            painter.setBrush(QColor('#d49a5f'))
            painter.drawEllipse(rect(-head, -head, head, head))
            pin = float(p['pin_radius_mm'])
            painter.drawRect(rect(-pin, 0, pin, float(p['pin_length_mm'])))
        else:
            body = float(p['body_length_mm'])/2
            painter.drawRect(rect(-radius, -body, radius, body))
            bore = float(p['bore_radius_mm'])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.palette().base())
            painter.drawRect(rect(-bore, -body, bore, body))
            pin = float(p['pin_radius_mm'])
            painter.setBrush(QColor('#d49a5f'))
            painter.drawRect(rect(-pin, bottom, pin, top))
        painter.setPen(self.palette().text().color())
        painter.drawText(10, 20, tr('joint_concept.section_caption'))


class JointConceptDialog(QDialog):
    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._source_paths: tuple[Path, ...] = ()
        self._source: dict[str, Any] | None = None
        self._candidate: dict[str, Any] | None = None
        self._revision = 0
        self._baseline: tuple[Any, ...] | None = None
        self._closing_confirmed = False
        self.setWindowTitle(tr('joint_concept.title'))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(740, 740)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget(scroll)
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        warning = QLabel(tr('joint_concept.warning'), self)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self._new = QPushButton(tr('joint_concept.new'), self)
        self._new.clicked.connect(self._new_draft)
        layout.addWidget(self._new)
        self._open = QPushButton(tr('joint_concept.open'), self)
        self._open.clicked.connect(self._open_file)
        layout.addWidget(self._open)
        self._source_label = QLabel(tr('joint_concept.draft'), self)
        self._source_label.setWordWrap(True)
        self._source_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._source_label)
        form = QFormLayout()
        self._kind = QComboBox(self)
        for kind in DEFAULTS:
            self._kind.addItem(tr(f'joint_concept.{kind}'), kind)
        form.addRow(tr('joint_concept.kind'), self._kind)
        layout.addLayout(form)
        self._stack = QStackedWidget(self)
        self._fields: dict[str, dict[str, QLineEdit]] = {}
        for kind, values in DEFAULTS.items():
            page = QWidget(self._stack)
            fields: dict[str, QLineEdit] = {}
            page_form = QFormLayout(page)
            for key, default in values.items():
                field = QLineEdit(str(default), page)
                field.setMaxLength(64)
                field.setAccessibleName(tr(f'joint_concept.{key}'))
                field.textChanged.connect(self._refresh)
                fields[key] = field
                page_form.addRow(tr(f'joint_concept.{key}'), field)
            self._fields[kind] = fields
            self._stack.addWidget(page)
        layout.addWidget(self._stack)
        limits = QLabel(tr('joint_concept.limits'), self)
        limits.setWordWrap(True)
        layout.addWidget(limits)
        self._last_kind = str(self._kind.currentData())
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._edit_status = QLabel(self)
        self._edit_status.setWordWrap(True)
        layout.addWidget(self._edit_status)
        tabs = QTabWidget(self)
        self._section = JointSection(tabs)
        tabs.addTab(self._section, tr('joint_concept.section'))
        self._three_d = Weldment3D(tabs, is_current=self._candidate_is_current, joint=True)
        tabs.addTab(self._three_d, tr('joint_concept.tab_3d'))
        layout.addWidget(tabs, 1)
        self._save = QPushButton(tr('joint_concept.save'), self)
        self._save.clicked.connect(self._save_copy)
        layout.addWidget(self._save)
        self._saved = QLabel(self)
        self._saved.setWordWrap(True)
        self._saved.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._saved)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._kind.currentIndexChanged.connect(self._kind_changed)
        self._three_d.availabilityChanged.connect(self._update_save)
        self._refresh()
        self._baseline = self._input_state()
        self._update_edit_status()

    def _state_for(self, kind: str) -> tuple[Any, ...]:
        return kind, tuple(field.text() for field in self._fields[kind].values())

    def _input_state(self) -> tuple[Any, ...]:
        return self._state_for(str(self._kind.currentData()))

    def _has_unsaved(self) -> bool:
        return self._baseline is not None and self._input_state() != self._baseline

    def _update_edit_status(self) -> None:
        self._edit_status.setText(tr('joint_concept.unsaved') if self._has_unsaved() else '')

    def _fill(self, kind: str, values: dict[str, Any]) -> None:
        blockers = [QSignalBlocker(field) for field in self._fields[kind].values()]
        try:
            for key, field in self._fields[kind].items():
                field.setText(str(values[key]))
        finally:
            for blocker in blockers:
                blocker.unblock()

    def _kind_changed(self, *_args: object) -> None:
        old, new = self._last_kind, str(self._kind.currentData())
        revision, old_state, new_state = self._revision, self._state_for(old), self._input_state()
        if self._baseline is not None and old_state != self._baseline:
            answer = QMessageBox.question(self, tr('weldment.discard_title'), tr('joint_concept.discard'),
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if (answer != QMessageBox.StandardButton.Yes or revision != self._revision or
                    old_state != self._state_for(old) or new_state != self._input_state()):
                with QSignalBlocker(self._kind):
                    self._kind.setCurrentIndex(self._kind.findData(old))
                return
        self._source, self._source_paths = None, ()
        self._fill(new, DEFAULTS[new])
        self._last_kind = new
        self._stack.setCurrentIndex(self._kind.currentIndex())
        self._source_label.setText(tr('joint_concept.draft'))
        self._baseline = self._input_state()
        self._refresh()

    def confirm_close(self) -> bool:
        if self._closing_confirmed or not self._has_unsaved():
            return True
        state, revision = self._input_state(), self._revision
        answer = QMessageBox.question(self, tr('weldment.discard_title'), tr('joint_concept.discard'),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes and state == self._input_state() and revision == self._revision

    def _new_draft(self) -> None:
        if not self.confirm_close():
            return
        kind = str(self._kind.currentData())
        self._source, self._source_paths = None, ()
        self._fill(kind, DEFAULTS[kind])
        self._baseline = self._input_state()
        self._source_label.setText(tr('joint_concept.draft'))
        self._refresh()

    def _open_file(self) -> None:
        state, revision = self._input_state(), self._revision
        selected, _ = QFileDialog.getOpenFileName(self, tr('joint_concept.open'), '', tr('arm_concept.assembly_filter'))
        if not selected:
            return
        if state != self._input_state() or revision != self._revision:
            QMessageBox.warning(self, tr('joint_concept.title'), tr('weldment.changed'))
            return
        try:
            path = Path(selected).absolute()
            resolved = path.resolve()
            doc = read_document(path, 'assembly')
            validate_joint_concept(doc)
        except (KimFormatError, OSError, ValueError, RuntimeError):
            QMessageBox.warning(self, tr('joint_concept.title'), tr('joint_concept.open_failed'))
            return
        if not self.confirm_close():
            return
        if state != self._input_state() or revision != self._revision:
            QMessageBox.warning(self, tr('joint_concept.title'), tr('weldment.changed'))
            return
        self._source, self._source_paths = doc, (path, resolved)
        kind = doc['joint_type']
        with QSignalBlocker(self._kind):
            self._kind.setCurrentIndex(self._kind.findData(kind))
        self._last_kind = kind
        self._stack.setCurrentIndex(self._kind.currentIndex())
        self._fill(kind, doc['parameters'])
        self._source_label.setText(tr('joint_concept.source', path=str(path), name=doc['name']))
        self._baseline = self._input_state()
        self._refresh()

    def _make_candidate(self) -> dict[str, Any]:
        kind = str(self._kind.currentData())
        try:
            values = {key: float(field.text().strip().replace(',', '.')) for key, field in self._fields[kind].items()}
        except ValueError as error:
            raise KimFormatError('missing dimensions') from error
        name = self._source['name'] if self._source else 'Условный шарнир'
        return make_joint_concept(kind, values, name=name)

    def _refresh(self, *_args: object) -> None:
        self._revision += 1
        self._saved.clear()
        self._candidate = None
        self._section.set_document(None)
        self._three_d.set_document(None)
        self._update_save()
        try:
            candidate = self._make_candidate()
        except (KimFormatError, ValueError, TypeError, OverflowError):
            self._status.setText(tr('joint_concept.invalid'))
            self._update_edit_status()
            return
        self._candidate = candidate
        self._section.set_document(candidate)
        self._three_d.set_document(candidate)
        self._status.setText(tr('joint_concept.ready'))
        self._update_save()
        self._update_edit_status()

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
        revision, generation, state = self._revision, self._three_d.generation, self._input_state()
        selected, _ = QFileDialog.getSaveFileName(self, tr('joint_concept.save'), '', tr('arm_concept.assembly_filter'))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kima':
            path = path.with_name(path.name + '.kima')
        if (revision != self._revision or generation != self._three_d.generation or state != self._input_state() or
                not self._three_d.can_save()):
            QMessageBox.warning(self, tr('joint_concept.title'), tr('weldment.changed'))
            return
        try:
            if not self._candidate_is_current(candidate):
                raise KimFormatError('inputs changed')
            if any(same_project_file(path, source) for source in self._source_paths):
                raise KimFormatError('source path')
            if self.controller.is_protected_export_target(path):
                raise KimFormatError('protected project')
            write_document(path, 'assembly', candidate, overwrite=False)
        except (KimFormatError, OSError, ValueError, TypeError, RuntimeError):
            QMessageBox.warning(self, tr('joint_concept.title'), tr('weldment.save_failed'))
            self._refresh()
            return
        self._baseline = self._input_state()
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
