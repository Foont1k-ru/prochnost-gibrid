"""Явный перенос выбранной точки приблизительной сетки во временную пару CAD."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core.cad_mesh import CadMesh
from ..i18n import tr
from .cad_preview_dialog import CadPreviewDialog


class CadRegistrationPicker(CadPreviewDialog):
    """Повторно открываемый просмотр: пользователь сам подтверждает A или B."""

    def __init__(self, settings: QSettings, parent=None) -> None:
        super().__init__(parent, settings=settings)
        self.chosen: tuple[float, float, float] | None = None
        self.chosen_digest: bytes | None = None
        self.setWindowTitle(tr("cad_registration.pick_title"))
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        note = QLabel(tr("cad_registration.pick_notice"), self)
        note.setWordWrap(True)
        layout.insertWidget(0, note)
        self._identity_note = QLabel(self)
        self._identity_note.setWordWrap(True)
        layout.insertWidget(1, self._identity_note)
        row = QHBoxLayout()
        self._use_a = QPushButton(tr("cad_registration.pick_a"), self)
        self._use_b = QPushButton(tr("cad_registration.pick_b"), self)
        self._use_a.clicked.connect(lambda: self._use_point(0))
        self._use_b.clicked.connect(lambda: self._use_point(1))
        row.addWidget(self._use_a)
        row.addWidget(self._use_b)
        row.addStretch()
        layout.insertLayout(layout.count() - 1, row)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        ready = self._reader is None and self._mesh is not None and self._loaded_digest is not None
        self._identity_note.setText(tr("cad_registration.pick_identity_missing") if
                                    self._mesh is not None and self._loaded_digest is None else "")
        self._use_a.setEnabled(ready and len(self._measurement_points) >= 1)
        self._use_b.setEnabled(ready and len(self._measurement_points) >= 2)

    def _use_point(self, index: int) -> None:
        if (self._reader is not None or self._mesh is None or self._loaded_digest is None or
                not 0 <= index < len(self._measurement_points)):
            return
        self.chosen = tuple(float(x) for x in self._measurement_points[index])  # type: ignore[assignment]
        self.chosen_digest = self._loaded_digest
        self.accept()

    def load_file(self, path: Path, *, force: bool = False) -> None:
        super().load_file(path, force=force)
        self._sync_buttons()

    def _update_measurement(self, missed: bool = False) -> None:
        super()._update_measurement(missed)
        if hasattr(self, "_use_a"):
            self._sync_buttons()

    def _show_mesh(self, mesh: CadMesh) -> None:
        super()._show_mesh(mesh)
        if not self._cancel_requested and self._mesh is mesh:
            self._measure.setChecked(True)
        self._sync_buttons()

    def _finished(self) -> None:
        super()._finished()
        self._sync_buttons()
