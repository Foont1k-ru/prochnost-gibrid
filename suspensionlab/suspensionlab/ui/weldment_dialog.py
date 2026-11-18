"""Просмотр снимка KIMA и явная работа с копией, без CAD и без привязки к файлу проекта."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..model.arm_concept import make_arm_concept
from ..model.autosave_guard import same_project_file
from ..model.kim_format import KimFormatError, read_document, write_document
from ..model.welded_arm import (
    preview_rebuild_welded_arm,
    validate_welded_arm,
    weldment_bends,
    weldment_centerlines,
    weldment_source_matches,
)
from .arm_concept_dialog import ArmConceptCanvas
from .bend_editor import BendEditor
from .controller import AppController
from .weldment_3d import Weldment3D


class WeldmentDialog(QDialog):
    """Не изменяет открытый файл или проект; сравнение только трёх точек и типа."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._source: dict[str, Any] | None = None
        self._source_paths: tuple[Path, ...] = ()
        self._candidate: dict[str, Any] | None = None
        self._active = False
        self._revision = 0
        self._baseline: tuple[tuple[bool, tuple[str, ...]], ...] = ()
        self._closing_confirmed = False
        self.setWindowTitle(tr("weldment.title"))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(730, 800)
        root = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)
        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        warning = QLabel(tr("weldment.warning"), self)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self._open = QPushButton(tr("weldment.open"), self)
        self._open.clicked.connect(self._open_file)
        layout.addWidget(self._open)
        self._file = QLabel(tr("weldment.no_file"), self)
        self._file.setWordWrap(True)
        self._file.setTextFormat(Qt.TextFormat.PlainText)
        self._file.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._file)
        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels([tr("weldment.tree_header")])
        self._tree.setMaximumHeight(170)
        layout.addWidget(self._tree)
        self._activate = QPushButton(tr("weldment.activate"), self)
        self._activate.clicked.connect(self._start_preview)
        self._activate.setEnabled(False)
        layout.addWidget(self._activate)
        self._status = QLabel(tr("weldment.inactive"), self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        bend_group = QGroupBox(tr("weldment.edit_bends"), self)
        bend_layout = QVBoxLayout(bend_group)
        self._bend_editor = BendEditor(bend_group)
        self._bend_editor.set_editable(False)
        bend_layout.addWidget(self._bend_editor)
        layout.addWidget(bend_group)
        self._edit_status = QLabel(self)
        self._edit_status.setWordWrap(True)
        layout.addWidget(self._edit_status)
        tabs = QTabWidget(self)
        self._canvas = ArmConceptCanvas(tabs)
        tabs.addTab(self._canvas, tr("weldment_3d.tab_2d"))
        self._three_d = Weldment3D(tabs, is_current=self._candidate_is_current)
        tabs.addTab(self._three_d, tr("weldment_3d.tab_3d"))
        layout.addWidget(tabs, 1)
        self._save = QPushButton(tr("weldment.save"), self)
        self._save.setEnabled(False)
        self._save.clicked.connect(self._save_copy)
        layout.addWidget(self._save)
        self._saved = QLabel(self)
        self._saved.setWordWrap(True)
        self._saved.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._saved)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._bend_editor.changed.connect(self._bend_changed)
        self._three_d.availabilityChanged.connect(self._update_save)
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._project_replaced)

    def _clear_preview(self) -> None:
        self._candidate = None
        self._canvas.set_concept(None)
        self._three_d.set_document(None)
        self._save.setEnabled(False)

    def _open_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, tr("weldment.open"), "", tr("arm_concept.assembly_filter"))
        if not selected:
            return
        if not self.confirm_close():
            return
        # A failed open cannot leave the previous file displayed as the new one.
        self._revision += 1
        self._active = False
        self._source = None
        self._source_paths = ()
        self._bend_editor.set_editable(False)
        self._bend_editor.load({})
        self._baseline = self._bend_editor.state()
        self._edit_status.clear()
        self._clear_preview()
        self._tree.clear()
        self._activate.setEnabled(False)
        self._file.setText(tr("weldment.no_file"))
        self._saved.clear()
        try:
            source_path = Path(selected).absolute()
            original_path = source_path.resolve()
            doc = read_document(source_path, "assembly")
            validate_welded_arm(doc)  # only the supported welded-arm graph
            matches = weldment_source_matches(doc)
        except (KimFormatError, OSError, ValueError, RuntimeError):
            self._status.setText(tr("weldment.open_failed"))
            return
        self._source = doc
        self._bend_editor.load(weldment_bends(doc))
        self._baseline = self._bend_editor.state()
        self._source_paths = (source_path, original_path)
        self._file.setText(tr("weldment.file", path=selected, name=doc["name"],
                              damper=tr(f"arm_concept.damper_{doc['damper_mount']}")))
        items: dict[str, QTreeWidgetItem] = {}
        for node in doc["nodes"]:
            label = tr(f"weldment.node_{node['role']}")
            if node["part_id"] is not None:
                part = next(part for part in doc["parts"] if part["id"] == node["part_id"])
                label += ": " + part["name"]
            item = QTreeWidgetItem([label])
            parent = node["parent"]
            if parent is None:
                self._tree.addTopLevelItem(item)
            else:
                items[parent].addChild(item)
            items[node["id"]] = item
        self._tree.expandAll()
        self._activate.setEnabled(matches)
        self._status.setText(tr("weldment.inactive" if matches else "weldment.stale"))

    def _start_preview(self) -> None:
        if self._source is None or not self._activate.isEnabled():
            return
        self._active = True
        self._bend_editor.set_editable(True)
        self._refresh()

    def _project_replaced(self) -> None:
        self._revision += 1
        self._active = False
        self._bend_editor.set_editable(False)
        self._clear_preview()
        self._saved.clear()
        if self._source is not None:
            self._status.setText(tr("weldment.replaced"))

    def _refresh(self, *_args: object) -> None:
        self._revision += 1
        self._saved.clear()
        self._clear_preview()
        if not self._active or self._source is None:
            return
        try:
            candidate, matches = preview_rebuild_welded_arm(self._source, self.controller.project,
                                                               bends=self._bend_editor.values())
            geometry = candidate["parts"][0]["geometry"]
            # The sketch limits are more restrictive than the file format.
            concept = make_arm_concept(self.controller.project, "tube", geometry["radius_mm"], geometry["wall_mm"], 3.)
        except (KimFormatError, ValueError, TypeError, OverflowError):
            self._status.setText(tr("weldment.invalid"))
            return
        self._candidate = candidate
        self._canvas.set_concept(concept, weldment_centerlines(candidate))
        self._three_d.set_document(candidate)
        self._update_save()
        self._status.setText(tr("weldment.match" if matches else "weldment.different"))

    def _candidate_is_current(self, candidate: dict[str, Any]) -> bool:
        if not self._active or self._source is None or candidate != self._candidate:
            return False
        try:
            fresh, _ = preview_rebuild_welded_arm(self._source, self.controller.project,
                                                    bends=self._bend_editor.values())
            return fresh == candidate
        except (KimFormatError, ValueError, TypeError, OverflowError):
            return False

    def _bend_changed(self) -> None:
        self._edit_status.setText(tr("weldment.edited") if self._bend_editor.state() != self._baseline else "")
        self._refresh()

    def confirm_close(self) -> bool:
        if self._closing_confirmed or self._source is None or self._bend_editor.state() == self._baseline:
            return True
        source, state = self._source, self._bend_editor.state()
        answer = QMessageBox.question(self, tr("weldment.discard_title"), tr("weldment.discard_text"),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return (answer == QMessageBox.StandardButton.Yes and self._source is source
                and self._bend_editor.state() == state)

    def _update_save(self, *_args: object) -> None:
        self._save.setEnabled(self._candidate is not None and self._active and self._three_d.can_save())

    def shutdown(self) -> bool:
        return self._three_d.shutdown()

    def reject(self) -> None:
        if not self.confirm_close():
            return
        if self.shutdown():
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

    def _save_copy(self) -> None:
        if self._candidate is None or self._source is None or not self._active or not self._three_d.can_save():
            return
        revision = self._revision
        generation = self._three_d.generation
        candidate = self._candidate
        selected, _ = QFileDialog.getSaveFileName(self, tr("weldment.save"), "", tr("arm_concept.assembly_filter"))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".kima":
            path = path.with_name(path.name + ".kima")
        if (revision != self._revision or generation != self._three_d.generation or
                not self._active or not self._three_d.can_save()):
            QMessageBox.warning(self, tr("weldment.title"), tr("weldment.changed"))
            return
        try:
            # Also catch unsignalled changes made while the native dialog was open.
            fresh, _ = preview_rebuild_welded_arm(self._source, self.controller.project,
                                                    bends=self._bend_editor.values())
            if fresh != candidate:
                raise KimFormatError("project changed")
            if any(same_project_file(path, source) for source in self._source_paths):
                raise KimFormatError("original source path")
            if self.controller.is_protected_export_target(path):
                raise KimFormatError("protected project")
            write_document(path, "assembly", candidate, overwrite=False)
        except (KimFormatError, OSError, ValueError, TypeError, RuntimeError):
            QMessageBox.warning(self, tr("weldment.title"), tr("weldment.save_failed"))
            self._refresh()
            return
        self._baseline = self._bend_editor.state()
        self._edit_status.clear()
        self._saved.setText(tr("weldment.saved", path=str(path)))
