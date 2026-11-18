"""Интерактивный просмотр статического условного каркаса проекта."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...core.vehicle_schematic_scene import vehicle_schematic_scene
from ...i18n import tr
from ..controller import AppController
from ..widgets.camera_views import CameraViews
from .scene3d_preview import Scene3DPreview


class VehicleSchematicView(QWidget):
    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
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
        controls.addStretch(1)
        layout.addLayout(controls)
        self.preview = Scene3DPreview(self, schematic=True)
        layout.addWidget(self.preview, 1)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.camera.viewSelected.connect(self.preview.set_standard_view)
        self.reset_button.clicked.connect(self.preview.reset_camera)
        self.volume_toggle.toggled.connect(self._set_volumetric)
        controller.modelChanged.connect(self.refresh)
        controller.projectReplaced.connect(self.refresh)
        self.refresh()

    def _set_volumetric(self, enabled: bool) -> None:
        self.preview.volumetric = enabled
        self.preview.update()

    def refresh(self) -> None:
        try:
            result = vehicle_schematic_scene(self.controller.project)
            self.preview.configure([result.scene])
            self.preview.show_frame(result.scene)
        except (ValueError, TypeError, OverflowError):
            self.preview.clear(tr("vehicle_schematic.invalid"))
            self.status.setText(tr("vehicle_schematic.invalid"))
            return
        self.status.setText(tr("vehicle_schematic.incomplete", count=len(result.missing)) if result.missing else "")

    def zoom_by(self, factor: float) -> None:
        self.preview.zoom = max(0.25, min(4.0, self.preview.zoom * factor))
        self.preview.update()
