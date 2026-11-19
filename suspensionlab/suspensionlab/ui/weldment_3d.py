"""Асинхронный частичный просмотр двух труб; старые результаты не показываются."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.cad_mesh import CadMesh
from ..core.cad_preview_parts import preview_parts
from ..core.cad_transport import CadPreviewError
from ..core.cad_weldment_job import WeldmentCadJob
from ..i18n import tr
from .canvas.cad_preview import CadPreview


class _TubeReader(QThread):
    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, document: dict[str, Any], token: int, parent: QWidget, deviation: float = 2.) -> None:
        super().__init__(parent)
        self.document = document
        self.token = token
        self.deviation = deviation
        self.job = WeldmentCadJob()

    def run(self) -> None:
        try:
            self.completed.emit(self.token, self.job.run(self.document, deviation=self.deviation))
        except CadPreviewError as error:
            self.failed.emit(self.token, error.code)
        except Exception:
            self.failed.emit(self.token, "unexpected")


class Weldment3D(QWidget):
    availabilityChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None, *,
                 is_current: Callable[[dict[str, Any]], bool] | None = None,
                 single_tube: bool = False, four_tubes: bool = False, joint: bool = False,
                 joint_layout: bool = False, rear_joint_layout: bool = False,
                 scheme_part: bool = False, fixed_skeleton: bool = False) -> None:
        super().__init__(parent)
        self._is_current = is_current
        self._single_tube = single_tube
        self._four_tubes = four_tubes
        self._joint = joint
        self._joint_layout = joint_layout
        self._rear_joint_layout = rear_joint_layout
        self._scheme_part = scheme_part
        self._fixed_skeleton = fixed_skeleton
        self._document: dict[str, Any] | None = None
        self._pending: dict[str, Any] | None = None
        self._worker: _TubeReader | None = None
        self._ready = False
        self._closed = False
        self.generation = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._start)
        layout = QVBoxLayout(self)
        enable_key = ("scheme_part_3d.enable" if scheme_part else
                      "rear_joint_layout.cad_enable" if rear_joint_layout else
                      "front_joint_layout.cad_enable" if joint_layout else "joint_concept.cad_enable" if joint else
                      "front_pair.cad_enable" if four_tubes else
                      "rear_tube.enable" if single_tube else "weldment_3d.enable")
        self._enable = QCheckBox(tr(enable_key), self)
        self._enable.toggled.connect(self._toggle)
        layout.addWidget(self._enable)
        quality_label = QLabel(tr("weldment_3d.quality_label"), self)
        quality_label.setWordWrap(True)
        layout.addWidget(quality_label)
        self._quality = QComboBox(self)
        self._quality.setAccessibleName(tr("weldment_3d.quality_accessible"))
        self._quality.addItem(tr("weldment_3d.quality_smooth"), 0.2)
        self._quality.addItem(tr("weldment_3d.quality_fast"), 2.0)
        self._quality.currentIndexChanged.connect(self._schedule)
        layout.addWidget(self._quality)
        self._status = QLabel(tr("weldment_3d.off"), self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._view = CadPreview(self, empty_text_key="weldment_3d.empty")
        self._parts_panel = QWidget(self)
        parts_layout = QVBoxLayout(self._parts_panel)
        parts_layout.setContentsMargins(0, 0, 0, 0)
        self._parts_filter = QLineEdit(self._parts_panel)
        self._parts_filter.setPlaceholderText(tr("weldment_3d.parts_filter"))
        self._parts_filter.setAccessibleName(tr("weldment_3d.parts_filter"))
        parts_layout.addWidget(self._parts_filter)
        self._parts_tree = QTreeWidget(self._parts_panel)
        self._parts_tree.setHeaderLabels([tr("weldment_3d.parts_header")])
        self._parts_tree.setMinimumWidth(170)
        parts_layout.addWidget(self._parts_tree, 1)
        hint = QLabel(tr("weldment_3d.parts_hint"), self._parts_panel)
        hint.setWordWrap(True)
        parts_layout.addWidget(hint)
        self._parts_panel.hide()
        self._parts_filter.textChanged.connect(self._filter_parts)
        self._parts_tree.currentItemChanged.connect(self._select_tree_part)
        self._view.triangle_picked.connect(self._pick_tree_part)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(self._parts_panel)
        split.addWidget(self._view)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self._retry = QPushButton(tr("weldment_3d.retry"), self)
        self._retry.setEnabled(False)
        self._retry.clicked.connect(self._restart)
        layout.addWidget(self._retry)
        self._reset = QPushButton(tr("weldment_3d.reset"), self)
        self._reset.clicked.connect(self._view.reset_camera)
        layout.addWidget(self._reset)

    def can_save(self) -> bool:
        return not self._closed and (not self._enable.isChecked() or self._ready)

    def _toggle(self, _checked: bool) -> None:
        self._schedule()

    def _restart(self) -> None:
        self._schedule()

    def set_document(self, document: dict[str, Any] | None) -> None:
        self._document = document
        self._schedule()

    def _schedule(self, *_args: object) -> None:
        self.generation += 1
        self._ready = False
        self._pending = None
        self._timer.stop()
        self._view.set_mesh(None)
        self._clear_parts()
        self._retry.setEnabled(False)
        if self._worker is not None:
            self._worker.job.cancel()
        if self._closed:
            self._status.setText(tr("weldment_3d.closing"))
        elif not self._enable.isChecked():
            self._status.setText(tr("weldment_3d.off"))
        elif self._document is None:
            self._status.setText(tr("weldment_3d.no_data"))
        else:
            self._pending = self._document
            building_key = ("weldment_3d.fixed_building" if self._fixed_skeleton else
                            "scheme_part_3d.building" if self._scheme_part else
                            "rear_joint_layout.cad_building" if self._rear_joint_layout else
                            "front_joint_layout.cad_building" if self._joint_layout else
                            "joint_concept.cad_building" if self._joint else
                            "front_pair.cad_building" if self._four_tubes else
                            "rear_tube.building" if self._single_tube else "weldment_3d.building")
            self._status.setText(tr(building_key))
            self._timer.start()
        self.availabilityChanged.emit(self.can_save())

    def _start(self) -> None:
        if self._worker is not None or self._pending is None or self._closed:
            return
        document, self._pending = self._pending, None
        worker = _TubeReader(document, self.generation, self, float(self._quality.currentData()))
        self._worker = worker
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()

    def _completed(self, token: int, mesh: object) -> None:
        if token != self.generation or self._closed or not self._enable.isChecked() or self._document is None:
            return
        if self._is_current is not None and not self._is_current(self._document):
            self._failed(token, "changed")
            return
        if not isinstance(mesh, CadMesh) or mesh.skipped_faces or mesh.recovered_faces:
            self._failed(token, "mesh")
            return
        descriptors = preview_parts(self._document)
        if descriptors:
            identifiers = tuple(part.identifier for part in descriptors)
            if (mesh.triangle_parts is None or mesh.part_names != identifiers or
                    any(not (mesh.triangle_parts == i).any() for i in range(len(identifiers)))):
                self._failed(token, "output")
                return
        self._view.set_mesh(mesh)
        self._populate_parts(mesh)
        self._ready = True
        self._retry.setEnabled(True)
        ready_key = ("scheme_part_3d.ready" if self._scheme_part else
                     "rear_joint_layout.cad_ready" if self._rear_joint_layout else
                     "front_joint_layout.cad_ready" if self._joint_layout else
                     "joint_concept.cad_ready" if self._joint else
                     "front_pair.cad_ready" if self._four_tubes else
                     "rear_tube.cad_ready" if self._single_tube else "weldment_3d.ready")
        self._status.setText(tr(ready_key, triangles=len(mesh.triangles)))
        self.availabilityChanged.emit(self.can_save())

    def _clear_parts(self) -> None:
        blocked = self._parts_tree.blockSignals(True)
        self._parts_tree.clear()
        self._parts_tree.blockSignals(blocked)
        self._parts_filter.clear()
        self._parts_panel.hide()

    def _populate_parts(self, mesh: CadMesh) -> None:
        self._clear_parts()
        if self._document is None or mesh.triangle_parts is None:
            return
        descriptors = preview_parts(self._document)
        if not descriptors:
            return
        root = QTreeWidgetItem([self._document.get('name', tr('weldment_3d.parts_root'))])
        self._parts_tree.addTopLevelItem(root)
        for index, part in enumerate(descriptors):
            name = part.name or tr(part.label_key)
            item = QTreeWidgetItem([f"{name} · {part.identifier}"])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setToolTip(0, item.text(0))
            root.addChild(item)
        root.setExpanded(True)
        self._parts_tree.setCurrentItem(root)
        self._parts_panel.show()

    def _filter_parts(self, text: str) -> None:
        root = self._parts_tree.topLevelItem(0)
        if root is None:
            return
        if self._is_current is not None and self._document is not None and not self._is_current(self._document):
            self._failed(self.generation, "changed")
            return
        query = text.strip().casefold()
        for index in range(root.childCount()):
            item = root.child(index)
            if item is not None:
                item.setHidden(bool(query) and query not in item.text(0).casefold())
        selected = self._parts_tree.currentItem()
        if selected is not None and selected.isHidden():
            self._parts_tree.setCurrentItem(root)
        root.setExpanded(True)

    def _select_tree_part(self, item: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        mesh = self._view.mesh
        if mesh is None or self._document is None or not preview_parts(self._document) or mesh.triangle_parts is None:
            return
        if self._is_current is not None and self._document is not None and not self._is_current(self._document):
            self._failed(self.generation, "changed")
            return
        index = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        highlight = mesh.triangle_parts == index if type(index) is int and 0 <= index < len(mesh.part_names) else None
        self._view.set_mesh(mesh, highlight)

    def _pick_tree_part(self, index: int) -> None:
        mesh = self._view.mesh
        root = self._parts_tree.topLevelItem(0)
        if (mesh is None or root is None or mesh.triangle_parts is None or
                not 0 <= index < len(mesh.triangles)):
            return
        if self._is_current is not None and self._document is not None and not self._is_current(self._document):
            self._failed(self.generation, "changed")
            return
        group = int(mesh.triangle_parts[index])
        if 0 <= group < root.childCount():
            item = root.child(group)
            if item is not None:
                if item.isHidden():
                    self._parts_filter.clear()
                self._parts_tree.setCurrentItem(item)

    def _failed(self, token: int, code: str) -> None:
        if token != self.generation or self._closed:
            return
        known = {"missing_cad", "timeout", "cancelled", "start", "crash", "mesh", "memory",
                 "missing_face", "coordinates", "no_faces", "no_shape", "output", "unexpected", "changed"}
        if code not in known:
            code = "unexpected"
        self._ready = False
        self._view.set_mesh(None)
        self._clear_parts()
        self._retry.setEnabled(self._document is not None and self._enable.isChecked())
        specific = {"timeout", "memory", "changed"}
        reason = tr(f"weldment_3d.error_{code}") if code in specific else tr(f"cad_preview.error.{code}")
        failed_key = ("weldment_3d.fixed_failed" if self._fixed_skeleton else
                      "scheme_part_3d.failed" if self._scheme_part else
                      "rear_joint_layout.cad_failed" if self._rear_joint_layout else
                      "front_joint_layout.cad_failed" if self._joint_layout else "weldment_3d.failed")
        self._status.setText(tr(failed_key, reason=reason))
        self.availabilityChanged.emit(self.can_save())

    def _finished(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        if self._pending is not None and not self._closed:
            self._timer.start()

    def shutdown(self) -> bool:
        """Остановить процесс перед уничтожением Qt-объектов; False — ещё завершается."""
        if not self._closed:
            self._closed = True
            self._schedule()
        if self._worker is None:
            return True
        self._worker.job.cancel()
        return bool(self._worker.wait(3000))
