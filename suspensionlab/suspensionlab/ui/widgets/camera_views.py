"""Меню команд направления камеры без состояния выбранной проекции."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from ...core.camera_views import CAMERA_VIEWS
from ...i18n import tr


class CameraViews(QToolButton):
    viewSelected = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, cad: bool = False) -> None:
        super().__init__(parent)
        self.setText(tr("camera_views.button"))
        self.setToolTip(tr("camera_views.cad_tip" if cad else "camera_views.scene_tip"))
        menu = QMenu(self)
        self.actions_by_view = {}
        prefix = "cad" if cad else "vehicle"
        for name in CAMERA_VIEWS:
            action = menu.addAction(tr(f"camera_views.{prefix}.{name}"))
            action.triggered.connect(lambda _checked=False, key=name: self.viewSelected.emit(key))
            self.actions_by_view[name] = action
        self.setMenu(menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
