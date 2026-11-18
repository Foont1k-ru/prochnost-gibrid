"""Интерактивный просмотр статического условного каркаса проекта."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from ...core.scene3d import Scene3D
from ...core.vehicle_schematic_pick import LinkHit
from ...core.vehicle_schematic_scene import vehicle_schematic_scene
from ...i18n import tr
from ..controller import AppController, Selection
from ..widgets.camera_views import CameraViews
from .scene3d_preview import Scene3DPreview


class VehicleSchematicView(QWidget):
    schemeRequested = Signal(str)
    linkSelected = Signal()

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._revision = 0
        self._focused_link: tuple[str, str] | None = None
        self._pick_menu: QMenu | None = None
        layout = QVBoxLayout(self)
        self.notice = QLabel(tr("vehicle_schematic.notice"), self)
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        controls = QHBoxLayout()
        self.camera = CameraViews(self)
        controls.addWidget(self.camera)
        self.volume_toggle = QCheckBox(tr("vehicle_schematic.volume"), self)
        self.volume_toggle.setToolTip(tr("vehicle_schematic.volume_tip"))
        self.volume_toggle.setChecked(True)
        controls.addWidget(self.volume_toggle)
        self.reset_button = QPushButton(tr("analysis.scene3d.reset"), self)
        controls.addWidget(self.reset_button)
        self.focus_button = QPushButton(tr("vehicle_schematic.focus"), self)
        self.focus_button.setToolTip(tr("vehicle_schematic.focus_tip"))
        self.focus_button.setEnabled(False)
        controls.addWidget(self.focus_button)
        self.show_all_button = QPushButton(tr("vehicle_schematic.show_all"), self)
        self.show_all_button.setEnabled(False)
        controls.addWidget(self.show_all_button)
        self.open_scheme = QPushButton(tr("vehicle_schematic.open_scheme"), self)
        self.open_scheme.setToolTip(tr("vehicle_schematic.open_scheme_tip"))
        self.open_scheme.setEnabled(False)
        controls.addWidget(self.open_scheme)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.preview = Scene3DPreview(self, schematic=True)
        layout.addWidget(self.preview, 1)
        self.selected_label = QLabel(tr("vehicle_schematic.pick_hint"), self)
        self.selected_label.setWordWrap(True)
        layout.addWidget(self.selected_label)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.camera.viewSelected.connect(self.preview.set_standard_view)
        self.reset_button.clicked.connect(self.preview.reset_camera)
        self.volume_toggle.toggled.connect(self._set_volumetric)
        self.preview.linksClicked.connect(self._choose_hits)
        self.open_scheme.clicked.connect(self._open_selected_scheme)
        self.focus_button.clicked.connect(self._focus_selection)
        self.show_all_button.clicked.connect(self._show_all)
        controller.selectionChanged.connect(self._sync_selection)
        controller.modelChanged.connect(self.refresh)
        controller.projectReplaced.connect(self.refresh)
        self.refresh()
        self._sync_selection(controller.selection)

    def _set_volumetric(self, enabled: bool) -> None:
        self.preview.volumetric = enabled
        self.preview.update()

    def _fit_bounds(self, key: tuple[str, str] | None, *, reset_scale: bool) -> bool:
        frame = self.preview.frame
        if frame is None:
            return False
        segments = tuple(link.segment for link in self.preview.link_targets if (link.role, link.code) == key)
        if key is not None and not segments:
            return False
        self.preview.configure([Scene3D(0., segments)] if key is not None else [frame])
        self._focused_link = key
        self.show_all_button.setEnabled(key is not None)
        if reset_scale:
            self.preview.zoom = 1.0
            self.preview.pan_x = self.preview.pan_y = 0.0
        self.preview.update()
        return True

    def _focus_selection(self) -> None:
        if self.preview.selected_link is not None:
            self._fit_bounds(self.preview.selected_link, reset_scale=True)

    def _show_all(self) -> None:
        self._fit_bounds(None, reset_scale=True)

    def _open_selected_scheme(self) -> None:
        selection = self.controller.selection
        if selection is not None and selection.kind == "link" and selection.role in ("front", "rear"):
            self.schemeRequested.emit(selection.role)

    def _choose_hits(self, hits: tuple[LinkHit, ...], position: QPoint) -> None:
        if not hits:
            return
        if len(hits) == 1:
            self._select_hit(hits[0], self._revision)
            return
        if self._pick_menu is not None:
            self._pick_menu.close()
        menu = QMenu(self)
        self._pick_menu = menu
        revision = self._revision
        for hit in hits:
            spec = self.controller.project.axle(hit.role).spec.link(hit.code)
            if spec is None:
                continue
            action = menu.addAction(f"{tr(f'tree.{hit.role}')} — {tr(spec.name_key)}")
            action.triggered.connect(lambda _checked=False, h=hit, r=revision: self._select_hit(h, r))
        menu.aboutToHide.connect(lambda: self._on_menu_hide(menu))
        menu.popup(self.preview.mapToGlobal(position))

    def _on_menu_hide(self, menu: QMenu) -> None:
        if self._pick_menu is menu:
            self._pick_menu = None
        menu.deleteLater()

    def _select_hit(self, hit: LinkHit, revision: int) -> None:
        if revision != self._revision or not any(link.role == hit.role and link.code == hit.code
                                                  for link in self.preview.link_targets):
            return
        self.controller.select(Selection("link", hit.role, hit.code))
        self.linkSelected.emit()

    def _sync_selection(self, selection: Selection | None) -> None:
        selected: tuple[str, str] | None = None
        if (selection is not None and selection.kind == "link" and selection.role in ("front", "rear")
                and any(link.role == selection.role and link.code == selection.code for link in self.preview.link_targets)):
            selected = (selection.role, selection.code)
        if self._focused_link is not None and selected != self._focused_link:
            self._fit_bounds(None, reset_scale=True)
            self._focused_link = None
            self.show_all_button.setEnabled(False)
        self.preview.selected_link = selected
        self.open_scheme.setEnabled(selected is not None)
        self.focus_button.setEnabled(selected is not None)
        if selected is None:
            self.selected_label.setText(tr("vehicle_schematic.pick_hint"))
        else:
            role, code = selected
            spec = self.controller.project.axle(role).spec.link(code)
            name = tr(spec.name_key) if spec is not None else code
            self.selected_label.setText(tr("vehicle_schematic.selected", axle=tr(f"tree.{role}"), name=name))
        self.preview.update()

    def refresh(self) -> None:
        self._revision += 1
        if self._pick_menu is not None:
            self._pick_menu.close()
            self._pick_menu = None
        try:
            result = vehicle_schematic_scene(self.controller.project)
            self.preview.configure([result.scene])
            self.preview.show_frame(result.scene)
            self.preview.link_targets = result.links
            if self._focused_link is not None and not self._fit_bounds(self._focused_link, reset_scale=False):
                self._focused_link = None
                self.show_all_button.setEnabled(False)
        except (ValueError, TypeError, OverflowError):
            self.preview.clear(tr("vehicle_schematic.invalid"))
            self._focused_link = None
            self.show_all_button.setEnabled(False)
            self.status.setText(tr("vehicle_schematic.invalid"))
            self._sync_selection(self.controller.selection)
            return
        self.status.setText(tr("vehicle_schematic.incomplete", count=len(result.missing)) if result.missing else "")
        self._sync_selection(self.controller.selection)

    def zoom_by(self, factor: float) -> None:
        self.preview.zoom = max(0.25, min(4.0, self.preview.zoom * factor))
        self.preview.update()
