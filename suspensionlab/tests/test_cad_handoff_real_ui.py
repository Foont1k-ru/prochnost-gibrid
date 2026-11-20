"""Предпросмотр переданной заготовки в существующем CAD-процессе."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

pytest.importorskip('OCP', reason='Опциональное CAD-ядро', exc_type=ImportError)

from suspensionlab.ui.cad_handoff_dialog import CadHandoffDialog  # noqa: E402
from suspensionlab.ui.clearance_dialog import ClearanceDialog  # noqa: E402
from suspensionlab.ui.main_window import MainWindow  # noqa: E402


def test_handoff_renders_real_cad_and_invalidates_on_project_edit(qtbot, tmp_path, monkeypatch):
    window = MainWindow(settings=QSettings(str(tmp_path / 'cad.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.controller.new_project('ring')
    window._tabs.setCurrentWidget(window._kinematics)
    window._show_workspace()
    window.show()
    view = window._kinematics
    qtbot.waitUntil(lambda: view.result is not None, timeout=10000)
    def clearance(dialog):
        dialog.refine.setChecked(False)
        for code, radius in (('lower_arm', 10.), ('tierod', 5.)):
            check, spin = dialog.links[code]
            check.setChecked(True)
            spin.setValue(radius)
        dialog.run_check()
        dialog.reject()
    monkeypatch.setattr(ClearanceDialog, 'exec', clearance)
    monkeypatch.setattr(CadHandoffDialog, 'exec', lambda _: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QInputDialog, 'getDouble', lambda *args: (2., True))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    before = window.controller.project.to_dict()
    view.clearance_button.click()
    view.cad_handoff_button.click()
    dialog = window._fixed_arm_skeleton_dialog
    assert dialog is not None and dialog.preview is not None
    dialog._cad._quality.setCurrentIndex(1)
    dialog._cad._enable.setChecked(True)
    qtbot.waitUntil(lambda: dialog._cad._ready, timeout=30000)
    assert dialog._cad._view.mesh is not None
    assert dialog._cad._view.mesh.part_names == ('tube_front', 'tube_rear')
    assert window.controller.project.to_dict() == before
    point = window.controller.project.front.hardpoints['lbj']
    window.controller.move_point(point, (point.x + 1, point.y, point.z))
    assert dialog.snapshot is None and dialog._cad._view.mesh is None
    assert dialog.shutdown()
    dialog.reject()
    qtbot.waitUntil(lambda: window._fixed_arm_skeleton_dialog is None, timeout=10000)
    window.controller.dirty = False
    window.close()
