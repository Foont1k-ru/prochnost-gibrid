"""Просмотр снимка KIMA и явная работа с копией, без CAD и без привязки к файлу проекта."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..model.arm_concept import make_arm_concept
from ..model.autosave_guard import same_project_file
from ..model.kim_format import KimFormatError, read_document, write_document
from ..model.welded_arm import preview_rebuild_welded_arm, validate_welded_arm, weldment_source_matches
from .arm_concept_dialog import ArmConceptCanvas
from .controller import AppController


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
        self.setWindowTitle(tr("weldment.title"))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(730, 800)
        layout = QVBoxLayout(self)
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
        self._canvas = ArmConceptCanvas(self)
        layout.addWidget(self._canvas, 1)
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
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._project_replaced)

    def _clear_preview(self) -> None:
        self._candidate = None
        self._canvas.set_concept(None)
        self._save.setEnabled(False)

    def _open_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, tr("weldment.open"), "", tr("arm_concept.assembly_filter"))
        if not selected:
            return
        # A failed open cannot leave the previous file displayed as the new one.
        self._revision += 1
        self._active = False
        self._source = None
        self._source_paths = ()
        self._clear_preview()
        self._tree.clear()
        self._activate.setEnabled(False)
        self._file.setText(tr("weldment.no_file"))
        self._saved.clear()
        try:
            source_path = Path(selected).absolute()
            original_path = source_path.resolve()
            doc = read_document(source_path, "assembly")
            validate_welded_arm(doc)  # only the supported 0.2 welded-arm graph
            matches = weldment_source_matches(doc)
        except (KimFormatError, OSError, ValueError, RuntimeError):
            self._status.setText(tr("weldment.open_failed"))
            return
        self._source = doc
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
        if self._source is None:
            return
        self._active = True
        self._refresh()

    def _project_replaced(self) -> None:
        self._revision += 1
        self._active = False
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
            candidate, matches = preview_rebuild_welded_arm(self._source, self.controller.project)
            geometry = candidate["parts"][0]["geometry"]
            # The sketch limits are more restrictive than the file format.
            concept = make_arm_concept(self.controller.project, "tube", geometry["radius_mm"], geometry["wall_mm"], 3.)
        except (KimFormatError, ValueError, TypeError, OverflowError):
            self._status.setText(tr("weldment.invalid"))
            return
        self._candidate = candidate
        self._canvas.set_concept(concept)
        self._save.setEnabled(True)
        self._status.setText(tr("weldment.match" if matches else "weldment.different"))

    def _save_copy(self) -> None:
        if self._candidate is None or self._source is None or not self._active:
            return
        revision = self._revision
        candidate = self._candidate
        selected, _ = QFileDialog.getSaveFileName(self, tr("weldment.save"), "", tr("arm_concept.assembly_filter"))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".kima":
            path = path.with_name(path.name + ".kima")
        if revision != self._revision or not self._active:
            QMessageBox.warning(self, tr("weldment.title"), tr("weldment.changed"))
            return
        try:
            # Also catch unsignalled changes made while the native dialog was open.
            fresh, _ = preview_rebuild_welded_arm(self._source, self.controller.project)
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
        self._saved.setText(tr("weldment.saved", path=str(path)))
